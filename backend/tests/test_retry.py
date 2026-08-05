"""Tests for app/db/retrievers.py — `_scroll_with_retry` retry/fail-fast.

This is the core of Bug #1 fix (Qdrant retrieval error handling). We
verify the two halves of the policy:
  - 5xx (and network errors / 429): retry with backoff up to max_attempts
  - 4xx (other than 429): fail fast (return False, 1 attempt)

We monkeypatch `asyncio.sleep` to keep the test instant — the real sleep
durations are exponential-and-jittered and would slow the suite to
seconds per case otherwise.
"""
import pytest
import asyncio
from app.db import retrievers


def _fake_status_exc(code: int):
    """A stand-in for qdrant_client's UnexpectedResponse: it exposes the
    `.status_code` attribute the retry policy reads."""
    class _E(Exception):
        status_code = code

        def __str__(self):
            return f"fake {code}"
    return _E("simulated")


async def mock_sleep(*args, **kwargs):
    pass


@pytest.mark.asyncio
async def test_retry_on_5xx_then_give_up(monkeypatch):
    monkeypatch.setattr(retrievers.asyncio, "sleep", mock_sleep)

    calls = {"n": 0}

    async def boom(*a, **k):
        calls["n"] += 1
        raise _fake_status_exc(500)

    ok, result = await retrievers._scroll_with_retry(boom, max_attempts=4, base_delay=0.01)
    assert ok is False
    assert calls["n"] == 4, f"expected 4 retry attempts, got {calls['n']}"


@pytest.mark.asyncio
async def test_retry_succeeds_eventually(monkeypatch):
    monkeypatch.setattr(retrievers.asyncio, "sleep", mock_sleep)

    attempts = {"n": 0}

    async def flaky(*a, **k):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise _fake_status_exc(503)
        # Return exactly (points_list, offset)
        return (["doc1", "doc2"], None)

    ok, result = await retrievers._scroll_with_retry(flaky, max_attempts=5, base_delay=0.01)
    assert ok is True
    assert attempts["n"] == 3
    assert result[0] == ["doc1", "doc2"]
    assert result[1] is None


@pytest.mark.asyncio
async def test_fail_fast_on_401(monkeypatch):
    """4xx other than 429 must NOT be retried — retrying auth errors is
    pointless and burns a round-trip on each request."""
    monkeypatch.setattr(retrievers.asyncio, "sleep", mock_sleep)
    calls = {"n": 0}

    async def boom_401(*a, **k):
        calls["n"] += 1
        raise _fake_status_exc(401)

    ok, _ = await retrievers._scroll_with_retry(boom_401, max_attempts=10, base_delay=1.0)
    assert ok is False
    assert calls["n"] == 1, f"401 should fail-fast (1 call), got {calls['n']}"


@pytest.mark.asyncio
async def test_retry_on_429(monkeypatch):
    """429 (TooManyRequests) is rate-limiting, not auth — it SHOULD be
    retried, not failed fast."""
    monkeypatch.setattr(retrievers.asyncio, "sleep", mock_sleep)
    calls = {"n": 0}

    async def boom_429(*a, **k):
        calls["n"] += 1
        if calls["n"] < 2:
            raise _fake_status_exc(429)
        return (["doc"], None)

    ok, result = await retrievers._scroll_with_retry(boom_429, max_attempts=3, base_delay=0.01)
    assert ok is True
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_no_status_code_treated_as_transient(monkeypatch):
    """A bare network error (no .status_code) is retried as transient."""
    monkeypatch.setattr(retrievers.asyncio, "sleep", mock_sleep)
    calls = {"n": 0}

    async def boom_network(*a, **k):
        calls["n"] += 1
        raise ConnectionError("Connection reset by peer")

    ok, _ = await retrievers._scroll_with_retry(boom_network, max_attempts=3, base_delay=0.01)
    assert ok is False
    assert calls["n"] == 3

"""Tests for API input validation & upload checks (Bug #2 / Task 5.2).

Pure-Python guards — no FastAPI httpx / LLM / Qdrant required.
"""
import pytest
from fastapi import HTTPException

from app.api import ask, ingest
from app.config import settings

# --- UserInput --------------------------------------------------------------

def test_query_max_length_enforced():
    too_long = "a" * (settings.MAX_QUERY_LEN + 1)
    with pytest.raises(Exception):
        ask.UserInput(query=too_long)


def test_query_control_bytes_stripped():
    # NUL (0x00) and DEL (0x7f) dropped; \n kept (multi-line clinical notes).
    u = ask.UserInput(query="hi\x00there\x7fmulti\nline")
    assert u.query == "hitheremulti\nline"


def test_query_strips_leading_trailing_whitespace():
    u = ask.UserInput(query="   what is covid?   ")
    assert u.query == "what is covid?"


def test_userinput_defaults():
    u = ask.UserInput(query="hello")
    assert u.session_id is None
    assert u.user_id is None


# --- _validate_upload -------------------------------------------------------

def test_validate_rejects_empty_upload():
    with pytest.raises(HTTPException) as exc_info:
        ingest._validate_upload(b"", "x.pdf")
    assert exc_info.value.status_code == 400


def test_validate_rejects_wrong_magic_bytes():
    with pytest.raises(HTTPException) as exc_info:
        ingest._validate_upload(b"#!/usr/bin/env python\nprint('pwned')", "evil.pdf")
    assert exc_info.value.status_code == 400
    assert "magic" in exc_info.value.detail.lower()


def test_validate_rejects_pdf_magic_mismatch():
    # .pdf extension but content is not a real PDF -> magic-header check fires.
    with pytest.raises(HTTPException) as exc_info:
        ingest._validate_upload(b"not a pdf body", "evil.pdf")
    assert exc_info.value.status_code == 400
    assert "magic" in exc_info.value.detail.lower()


def test_validate_rejects_oversized():
    cap = settings.MAX_PDF_SIZE_MB * 1024 * 1024
    with pytest.raises(HTTPException) as exc_info:
        ingest._validate_upload(b"%PDF-" + b"x" * (cap + 1 - len(b"%PDF-")), "big.pdf")
    assert exc_info.value.status_code == 413


def test_validate_accepts_valid_pdf():
    ingest._validate_upload(b"%PDF-1.4 hello", "ok.pdf")


def test_validate_accepts_txt_and_image_extensions():
    # No magic-byte check for text/image types — extension + size only.
    ingest._validate_upload(b"hello world", "notes.txt")
    ingest._validate_upload(b"\x89PNG\r\n\x1a\n", "scan.png")


def test_validate_rejects_unsupported_extension():
    with pytest.raises(HTTPException) as exc_info:
        ingest._validate_upload(b"whatever", "evil.exe")
    assert exc_info.value.status_code == 400
    assert "unsupported" in exc_info.value.detail.lower()


# --- _check_rate_limit ------------------------------------------------------

def test_rate_limit_allows_under_cap():
    ask._session_hits.clear()
    cap = settings.MAX_RPM_PER_SESSION
    for _ in range(cap):
        try:
            ask._check_rate_limit("sess-fresh")
        except HTTPException as e:
            pytest.fail(f"rate limit hit early: {e.detail}")


def test_rate_limit_returns_429_at_cap_plus_one():
    ask._session_hits.clear()
    cap = settings.MAX_RPM_PER_SESSION
    for _ in range(cap):
        ask._check_rate_limit("sess-cap")
    with pytest.raises(HTTPException) as exc_info:
        ask._check_rate_limit("sess-cap")
    assert exc_info.value.status_code == 429


def test_rate_limit_independent_per_session():
    ask._session_hits.clear()
    cap = settings.MAX_RPM_PER_SESSION
    for _ in range(cap):
        ask._check_rate_limit("sess-a")
    try:
        ask._check_rate_limit("sess-b")
    except HTTPException as e:
        pytest.fail(f"rate limit leaked across sessions: {e.detail}")
    with pytest.raises(HTTPException) as exc_info:
        ask._check_rate_limit("sess-a")
    assert exc_info.value.status_code == 429

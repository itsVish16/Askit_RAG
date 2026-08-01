"""Tests for app/core/security.py — bcrypt hashing + JWT round-trip."""
import pytest

from app.core.security import create_jwt, decode_jwt, hash_password, verify_password


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch):
    monkeypatch.setattr("app.config.settings.JWT_SECRET", "test-secret-key")


def test_hash_and_verify_password():
    h = hash_password("s3cret-pass")
    assert h != "s3cret-pass"
    assert verify_password("s3cret-pass", h) is True
    assert verify_password("wrong", h) is False


def test_hash_is_salt_randomized():
    assert hash_password("same-pass") != hash_password("same-pass")


def test_jwt_round_trip():
    token = create_jwt("user-123")
    assert decode_jwt(token) == "user-123"


def test_decode_invalid_token_returns_none():
    assert decode_jwt("not.a.jwt") is None
    assert decode_jwt("garbage") is None


def test_decode_token_signed_with_other_secret(monkeypatch):
    token = create_jwt("user-123")
    monkeypatch.setattr("app.config.settings.JWT_SECRET", "different-secret")
    assert decode_jwt(token) is None

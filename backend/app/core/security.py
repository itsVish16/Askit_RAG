"""Password hashing (bcrypt) and JWT issue/verification."""

from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from pydantic import BaseModel

from app.config import settings


class UserPublic(BaseModel):
    id: str
    name: str
    email: str


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def create_jwt(user_id: str, expires_hours: int | None = None) -> str:
    now = datetime.now(UTC)
    ttl = settings.JWT_EXPIRE_HOURS if expires_hours is None else expires_hours
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(hours=ttl),
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALG)
    return token if isinstance(token, str) else token.decode()


def decode_jwt(token: str) -> str | None:
    """Return user_id (`sub`) if valid and unexpired, else None."""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALG],
            options={"require": ["exp", "sub"]},
        )
        return payload.get("sub")
    except jwt.PyJWTError:
        return None

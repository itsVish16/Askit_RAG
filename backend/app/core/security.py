"""Password hashing (bcrypt) + JWT issue/verify."""

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


def create_jwt(user_id: str) -> str:
    payload = {"sub": user_id}
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALG)
    # PyJWT >=2 returns str; older versions return bytes — normalize.
    return token if isinstance(token, str) else token.decode()


def decode_jwt(token: str) -> str | None:
    """Return user_id (`sub`) if valid, else None."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALG])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None

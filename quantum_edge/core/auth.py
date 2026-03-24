"""JWT authentication for the Quantum Edge API."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from quantum_edge.core.config import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

ALGORITHM = "HS256"


def create_access_token(username: str, expires_delta: timedelta | None = None) -> str:
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(hours=settings.qe_jwt_expire_hours))
    payload = {"sub": username, "exp": expire}
    return jwt.encode(payload, settings.qe_jwt_secret, algorithm=ALGORITHM)


def verify_token(token: str) -> str:
    """Decode JWT and return the username. Raises on invalid/expired tokens."""
    try:
        payload = jwt.decode(token, settings.qe_jwt_secret, algorithms=[ALGORITHM])
        username: str | None = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        return username
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


async def get_current_user(token: str = Depends(oauth2_scheme)) -> str:
    """FastAPI dependency — validates Bearer token, returns username."""
    return verify_token(token)

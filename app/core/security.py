from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from app.core.config import settings
import hashlib
import base64

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _normalize_password(password: str) -> str:
    """
    Normalize password by pre-hashing with SHA256 to handle bcrypt's 72-byte limit.
    This ensures passwords of any length can be safely hashed.
    """
    # Hash the password with SHA256 and encode as base64
    password_hash = hashlib.sha256(password.encode('utf-8')).digest()
    return base64.b64encode(password_hash).decode('ascii')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash"""
    normalized = _normalize_password(plain_password)
    return pwd_context.verify(normalized, hashed_password)


def get_password_hash(password: str) -> str:
    """Generate password hash"""
    normalized = _normalize_password(password)
    return pwd_context.hash(normalized)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    """Decode and verify JWT token"""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        return None

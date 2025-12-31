from datetime import datetime, timedelta, timezone
import uuid

from jose import jwt
from passlib.context import CryptContext

from .config import settings

# Use Argon2 instead of bcrypt (more reliable on Python 3.13)
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)


def create_access_token(subject: str, expires_minutes: int) -> str:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=expires_minutes)
    jti = str(uuid.uuid4())

    payload = {
        "sub": subject,
        "exp": exp,
        "iat": now,
        "jti": jti,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
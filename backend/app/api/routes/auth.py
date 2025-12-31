from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlmodel import Session, select

from app.core.database import get_session
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    decode_token,
)
from app.core.config import settings
from app.models import User, RevokedToken
from app.schemas.auth import SignupIn, LoginIn, TokenOut


router = APIRouter(prefix="/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=True)


@router.post("/signup", response_model=TokenOut, status_code=201)
def signup(payload: SignupIn, session: Session = Depends(get_session)):
    # TEMPORARY DEBUG LINE
    print("PASSWORD BYTES:", len(payload.password.encode("utf-8")))

    existing = session.exec(
        select(User).where(User.email == payload.email)
    ).first()

    if existing:
        raise HTTPException(
            status_code=400,
            detail="Email already registered"
        )

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password)
    )

    session.add(user)
    session.commit()

    token = create_access_token(
        subject=payload.email,
        expires_minutes=settings.jwt_expire_minutes
    )

    return TokenOut(access_token=token)


@router.post("/", response_model=TokenOut)
def login(payload: LoginIn, session: Session = Depends(get_session)):
    user = session.exec(
        select(User).where(User.email == payload.email)
    ).first()

    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )

    token = create_access_token(
        subject=user.email,
        expires_minutes=settings.jwt_expire_minutes
    )

    return TokenOut(access_token=token)


@router.post("/logout")
def logout(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
    session: Session = Depends(get_session),
):
    token = creds.credentials

    try:
        payload = decode_token(token)
        jti = payload.get("jti")
        if not jti:
            raise ValueError("Missing jti")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    exists = session.exec(
        select(RevokedToken).where(RevokedToken.jti == jti)
    ).first()

    if not exists:
        session.add(RevokedToken(jti=jti))
        session.commit()

    return {"message": "Logged out"}

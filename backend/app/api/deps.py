from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlmodel import Session, select

from app.core.database import get_session
from app.core.security import decode_token
from app.models import User, RevokedToken

bearer = HTTPBearer(auto_error=True)

def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
    session: Session = Depends(get_session),
) -> User:
    token = creds.credentials
    try:
        payload = decode_token(token)
        user_email = payload.get("sub")
        jti = payload.get("jti")
        if not user_email or not jti:
            raise ValueError("Missing sub/jti")
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    revoked = session.exec(select(RevokedToken).where(RevokedToken.jti == jti)).first()
    if revoked:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked")

    user = session.exec(select(User).where(User.email == user_email)).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return user

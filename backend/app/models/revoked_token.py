from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime, timezone

class RevokedToken(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    jti: str = Field(index=True, unique=True)
    revoked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

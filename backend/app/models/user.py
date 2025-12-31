from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime, timezone

class User(SQLModel, table=True):
    __tablename__ = "users"   # ✅ IMPORTANT

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    password_hash: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
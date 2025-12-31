from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime, timezone

class ChatMessage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)

    role: str  # "user" | "assistant"
    content: str

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

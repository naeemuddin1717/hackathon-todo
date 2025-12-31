from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime, timezone

class Todo(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)

    title: str
    description: str | None = None
    completed: bool = False

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

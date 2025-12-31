from sqlmodel import SQLModel, create_engine, Session
from .config import settings

engine = create_engine(settings.database_url, echo=False, pool_pre_ping=True)

def init_db() -> None:
    # IMPORTANT: Import models so metadata contains tables
    import app.models  # noqa: F401
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session

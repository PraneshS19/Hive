from collections.abc import Generator

from app.core.config import settings
from app.db.base import enforce_sqlite_foreign_keys
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# SQLite connection args for multithreaded FastAPI handling
connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
    echo=False
)
enforce_sqlite_foreign_keys(engine)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

from datetime import UTC, datetime

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase


def get_utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


def enforce_sqlite_foreign_keys(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        return

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record) -> None:
        cursor = connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            if cursor.execute("PRAGMA foreign_keys").fetchone() != (1,):
                raise RuntimeError("Unable to enable SQLite foreign-key enforcement.")
        finally:
            cursor.close()

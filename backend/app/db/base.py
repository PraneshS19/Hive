from datetime import UTC, datetime

from sqlalchemy.orm import DeclarativeBase


def get_utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass

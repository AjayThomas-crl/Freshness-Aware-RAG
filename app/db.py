from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

IS_SQLITE = settings.database_url.startswith("sqlite")

# `timeout` is the sqlite3 busy-wait (seconds) before "database is locked".
connect_args = {"check_same_thread": False, "timeout": 30} if IS_SQLITE else {}

engine = create_engine(settings.database_url, connect_args=connect_args)


def _set_sqlite_pragmas(dbapi_connection, connection_record):
    """WAL lets readers run during writes; busy_timeout makes writers wait, not fail."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


if IS_SQLITE:
    event.listen(engine, "connect", _set_sqlite_pragmas)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from app import models  # noqa: F401  ensure models registered

    Base.metadata.create_all(bind=engine)

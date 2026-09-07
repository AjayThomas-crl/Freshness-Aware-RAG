import pytest

from app.db import IS_SQLITE, engine


@pytest.mark.skipif(not IS_SQLITE, reason="SQLite-only pragmas")
def test_sqlite_wal_and_busy_timeout_applied():
    with engine.connect() as conn:
        journal = conn.exec_driver_sql("PRAGMA journal_mode").scalar()
        busy = conn.exec_driver_sql("PRAGMA busy_timeout").scalar()
    assert str(journal).lower() == "wal"
    assert busy == 30000

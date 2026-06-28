import pytest

from time_tracker.db import Database


@pytest.fixture
def db() -> Database:
    """An in-memory database, fresh per test."""
    database = Database(":memory:")
    yield database
    database.close()

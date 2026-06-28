import os
import time

import pytest

from time_tracker.db import Database

# Pin the local timezone to UTC by default so the bulk of tests (which use UTC
# datetimes) are deterministic. Timezone-specific behaviour is covered in
# test_timezone.py, which sets its own zone.
os.environ["TZ"] = "UTC"
time.tzset()


@pytest.fixture
def db() -> Database:
    """An in-memory database, fresh per test."""
    database = Database(":memory:")
    yield database
    database.close()

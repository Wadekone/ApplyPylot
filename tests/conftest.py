import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Point the app at an empty throwaway SQLite database."""
    monkeypatch.setenv("APPLYPYLOT_DB_PATH", str(tmp_path / "test.db"))
    from database import init_db
    init_db()
    return tmp_path / "test.db"

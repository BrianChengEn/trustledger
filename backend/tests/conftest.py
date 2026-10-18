import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path):
    settings = Settings(_env_file=None, database_path=tmp_path / "test.db", allow_memory_write=True)
    with TestClient(create_app(settings)) as c:
        yield c

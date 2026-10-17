import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path):
    settings = Settings(_env_file=None, database_path=tmp_path / "test.db", allow_memory_write=True)
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture(autouse=True)
def deny_external_network(monkeypatch):
    """Block Python internet sockets/DNS, even when fallback swallows the exception."""
    import socket

    attempts = []
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def denied(*args, **kwargs):
        attempts.append("network attempt")  # Never retain addresses or credentials.
        raise AssertionError("External network access is forbidden in backend tests")

    def connect(sock, *args, **kwargs):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            return denied()
        return original_connect(sock, *args, **kwargs)

    def connect_ex(sock, *args, **kwargs):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            return denied()
        return original_connect_ex(sock, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    yield
    assert not attempts, "A test attempted external network access (possibly swallowed by fallback)"

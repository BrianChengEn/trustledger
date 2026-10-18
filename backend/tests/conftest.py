import os

# Isolated automated tests explicitly opt into fixtures. Runtime defaults remain live.
os.environ['APP_ENV'] = 'test'
os.environ['TRANSACTION_PROVIDER'] = 'synthetic'

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path):
    settings = Settings(_env_file=None, database_path=tmp_path / "test.db", allow_memory_write=True,
                        backboard_api_key="", jev_api_key="", nessie_api_key="")
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture(autouse=True)
def deny_external_network(monkeypatch, request):
    """Block Python internet sockets/DNS, even when fallback swallows the exception."""
    if request.node.get_closest_marker("live_network"):
        yield
        return
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

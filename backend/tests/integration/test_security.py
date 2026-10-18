import asyncio
import json
import logging

import pytest
from pydantic import SecretStr, ValidationError
from starlette.exceptions import HTTPException

from app.core.config import Settings
from app.core.http import BODY_LIMIT, RequestGuardMiddleware
from app.schemas.api import ErrorEnvelope

ORIGIN = "http://localhost:5173"
SENSITIVE = "synthetic-private-marker"


def headers(response):
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    rid = response.headers["x-request-id"]
    assert len(rid) == 32 and int(rid, 16) >= 0
    return rid


def error(response, status, code):
    assert response.status_code == status
    envelope = ErrorEnvelope.model_validate(response.json())
    assert envelope.error.code == code
    assert envelope.error.request_id == headers(response)
    assert SENSITIVE not in response.text


def raw_request(app, chunks, request_headers=(), method="POST", path="/api/v1/analyses",
                disconnect=False):
    """Exercise actual ASGI frames; HTTP clients may rewrite framing headers."""
    messages = []
    reads = 0

    async def run():
        nonlocal reads
        frames = [{"type": "http.request", "body": chunk,
                   "more_body": i < len(chunks) - 1 or disconnect}
                  for i, chunk in enumerate(chunks)]
        if disconnect:
            frames.append({"type": "http.disconnect"})

        async def receive():
            nonlocal reads
            reads += 1
            assert frames, "Middleware consumed the request more than once"
            return frames.pop(0)

        async def send(message):
            messages.append(message)

        await app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                   "method": method, "scheme": "http", "path": path,
                   "raw_path": path.encode(), "query_string": b"", "root_path": "",
                   "headers": [(b"content-type", b"application/json"), *request_headers],
                   "client": ("127.0.0.1", 1234), "server": ("test", 80)}, receive, send)
    asyncio.run(run())
    return messages, reads


def raw_error(messages, status, code):
    start, body = messages
    assert start["status"] == status
    hdr = dict(start["headers"])
    assert hdr[b"cache-control"] == b"no-store"
    assert hdr[b"x-content-type-options"] == b"nosniff"
    payload = json.loads(body["body"])
    ErrorEnvelope.model_validate(payload)
    assert payload["error"]["code"] == code
    assert payload["error"]["request_id"] == hdr[b"x-request-id"].decode()
    assert SENSITIVE.encode() not in body["body"]


@pytest.mark.parametrize("declared", [None, b"1", b"16385"])
def test_actual_oversize(client, declared):
    request_headers = [] if declared is None else [(b"content-length", declared)]
    messages, reads = raw_request(client.app, [b"x" * BODY_LIMIT, b"x", b"unread"], request_headers)
    raw_error(messages, 413, "request_too_large")
    assert reads == (0 if declared == b"16385" else 2)


@pytest.mark.parametrize("size", [b"-1", b"no", b"", b"9" * 5000, b"1, 1"])
def test_bad_length_header(client, size):
    messages, reads = raw_request(client.app, [b"{}"], [(b"content-length", size)])
    raw_error(messages, 413, "request_too_large")
    assert reads == 0


def test_duplicate_length_header(client):
    messages, reads = raw_request(client.app, [b"{}"], [(b"content-length", b"2")] * 2)
    raw_error(messages, 413, "request_too_large")
    assert reads == 0


@pytest.mark.parametrize("declared", [b"0", b"1", b"100"])
def test_incorrect_length(client, declared):
    messages, _ = raw_request(client.app, [b"{}"], [(b"content-length", declared)])
    raw_error(messages, 400, "invalid_request")


@pytest.mark.parametrize("framing", [[], [(b"transfer-encoding", b"chunked")],
                                     [(b"content-length", str(BODY_LIMIT).encode())]])
def test_limit_boundary_and_normal_parsing(client, framing):
    body = b'{"transaction_id":"txn_syn_004"}'
    body += b" " * (BODY_LIMIT - len(body))
    messages, reads = raw_request(client.app, [body[:10], b"", body[10:]], framing)
    assert reads == 3
    assert messages[0]["status"] == 200
    assert json.loads(messages[1]["body"])["transaction_id"] == "txn_syn_004"


def test_limit_counts_utf8_bytes(client):
    body = ('{"transaction_id":"' + "é" * 9000 + '"}').encode()
    messages, _ = raw_request(client.app, [body])
    raw_error(messages, 413, "request_too_large")


def test_oversize_confirmation_has_no_side_effect(client):
    body = b'{"decision":"normal","consent_to_memory":true}' + b" " * BODY_LIMIT
    messages, _ = raw_request(client.app, [body], path="/api/v1/alerts/alert_txn_syn_004/confirmations")
    raw_error(messages, 413, "request_too_large")
    assert client.get("/api/v1/memories").json() == []
    assert client.app.state.store.status(client.app.state.settings.demo_user_id,
                                         "alert_txn_syn_004") == "open"


def test_disconnect_does_not_dispatch(client):
    messages, reads = raw_request(client.app, [b"{"], disconnect=True)
    assert messages == [] and reads == 2


@pytest.mark.parametrize("status", [200, 403, 404, 405, 409, 413, 422, 500])
def test_headers_errors_cors_and_safe_logs(client, monkeypatch, caplog, status):
    caplog.set_level(logging.INFO, logger="app.core.http")
    request_headers = {"origin": ORIGIN, "x-request-id": SENSITIVE}
    if status == 200:
        response = client.get("/api/v1/health", headers=request_headers)
    elif status == 403:
        response = client.post("/api/v1/analyses", json={},
                               headers={**request_headers, "origin": "https://blocked.example"})
    elif status == 404:
        response = client.get("/api/v1/missing", headers=request_headers)
    elif status == 405:
        response = client.post("/api/v1/health", headers=request_headers)
    elif status == 409:
        path = "/api/v1/alerts/alert_txn_syn_004/confirmations"
        client.post(path, json={"decision": "normal", "consent_to_memory": False})
        response = client.post(path, json={"decision": "review", "consent_to_memory": False},
                               headers=request_headers)
    elif status == 413:
        response = client.post("/api/v1/analyses", content=SENSITIVE * 2000, headers=request_headers)
    elif status == 422:
        response = client.post("/api/v1/analyses", content='{"' + SENSITIVE,
                               headers=request_headers)
    else:
        def fail(*args):
            raise RuntimeError(f"https://vendor.invalid/?key={SENSITIVE} acct_private MerchantPrivate")
        monkeypatch.setattr(client.app.state.store, "list_memories", fail)
        response = client.get("/api/v1/memories", headers=request_headers)
    assert response.status_code == status
    rid = headers(response)
    if status != 200:
        assert ErrorEnvelope.model_validate(response.json()).error.request_id == rid
    else:
        assert response.json()["request_id"] == rid
    assert SENSITIVE not in response.text
    if status != 403:
        assert response.headers["access-control-allow-origin"] == ORIGIN
    else:
        assert "access-control-allow-origin" not in response.headers
    records = [r for r in caplog.records if r.name == "app.core.http"]
    assert records[-1].request_id == rid and records[-1].status_code == status
    assert all(r.getMessage() == "api_response" and r.exc_info is None for r in records)
    for marker in [SENSITIVE, "key=", "acct_private", "MerchantPrivate"]:
        assert marker not in caplog.text


@pytest.mark.parametrize("detail", [SENSITIVE, {"raw": SENSITIVE}])
def test_http_exception_details_are_not_codes(client, monkeypatch, detail):
    def fail(*args):
        raise HTTPException(400, detail, headers={"x-private": SENSITIVE})
    monkeypatch.setattr(client.app.state.store, "list_memories", fail)
    response = client.get("/api/v1/memories")
    error(response, 400, "request_failed")
    assert "x-private" not in response.headers


@pytest.mark.parametrize("origin,allowed", [(ORIGIN, True), ("http://127.0.0.1:5173", True),
                                           ("https://blocked.example", False)])
def test_cors_preflight(client, origin, allowed):
    response = client.options("/api/v1/analyses", headers={
        "origin": origin, "access-control-request-method": "POST",
        "access-control-request-headers": "content-type",
    })
    assert response.status_code == (200 if allowed else 400)
    headers(response)
    assert ("access-control-allow-origin" in response.headers) == allowed
    assert "access-control-allow-credentials" not in response.headers


def test_oversize_preflight_is_limited(client):
    messages, _ = raw_request(client.app, [b"x" * (BODY_LIMIT + 1)],
                              [(b"origin", ORIGIN.encode()),
                               (b"access-control-request-method", b"POST")], method="OPTIONS")
    raw_error(messages, 413, "request_too_large")


def test_delete_204_headers_and_unique_ids(client):
    confirmation = client.post("/api/v1/alerts/alert_txn_syn_004/confirmations",
                               json={"decision": "normal", "consent_to_memory": True})
    response = client.delete("/api/v1/memories/" + confirmation.json()["memory_id"])
    assert response.status_code == 204 and response.content == b""
    assert headers(response) != headers(confirmation)


@pytest.mark.parametrize("origin", ["*", "http://*.example", "null", "file:///tmp", "http://",
                                    "http://localhost:5173/", "https://user:pass@example.com",
                                    "https://example.com?key=private", "https://example.com/#frag"])
def test_invalid_cors_configuration(origin):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, frontend_origin=origin)


def test_secrets_remain_masked():
    settings = Settings(_env_file=None, nessie_api_key=SENSITIVE, jev_api_key=SENSITIVE,
                        backboard_api_key=SENSITIVE, gemini_api_key=SENSITIVE)
    assert isinstance(settings.nessie_api_key, SecretStr)
    assert SENSITIVE not in repr(settings)
    assert SENSITIVE not in settings.model_dump_json()


def test_non_http_scope_passes_through():
    seen = []

    async def app(scope, receive, send):
        seen.append(scope["type"])

    asyncio.run(RequestGuardMiddleware(app, [ORIGIN])({"type": "lifespan"}, None, None))
    assert seen == ["lifespan"]


def test_chunked_oversize_without_content_length(client):
    messages, reads = raw_request(client.app, [b"x" * BODY_LIMIT, b"x", b"unread"],
                                  [(b"transfer-encoding", b"chunked")])
    raw_error(messages, 413, "request_too_large")
    assert reads == 2


def test_blocked_delete_preserves_memory(client):
    confirmation = client.post("/api/v1/alerts/alert_txn_syn_004/confirmations",
                               json={"decision": "normal", "consent_to_memory": True})
    response = client.delete("/api/v1/memories/" + confirmation.json()["memory_id"],
                             headers={"origin": "https://blocked.example"})
    error(response, 403, "origin_denied")
    assert len(client.get("/api/v1/memories").json()) == 1


def test_custom_exact_origin_is_preserved(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app

    origin = "http://localhost:5174"
    settings = Settings(_env_file=None, frontend_origin=origin, database_path=tmp_path / "cors.db")
    with TestClient(create_app(settings)) as client:
        for size, status in [(1, 422), (BODY_LIMIT + 1, 413)]:
            response = client.post("/api/v1/analyses", content=b"x" * size,
                                   headers={"origin": origin})
            assert response.status_code == status
            assert response.headers["access-control-allow-origin"] == origin
            headers(response)


def test_asgi_replay_disconnect_and_response_streaming():
    received = []

    async def app(scope, receive, send):
        received.append(await receive())
        received.append(await receive())
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"first", "more_body": True})
        await send({"type": "http.response.body", "body": b"last", "more_body": False})

    async def run():
        frames = iter([{"type": "http.request", "body": b"a", "more_body": True},
                       {"type": "http.request", "body": b"b", "more_body": False},
                       {"type": "http.disconnect"}])
        sent = []

        async def receive():
            return next(frames)

        async def send(message):
            sent.append(message)

        await RequestGuardMiddleware(app, [ORIGIN])(
            {"type": "http", "method": "POST", "headers": []}, receive, send)
        return sent

    sent = asyncio.run(run())
    assert received == [{"type": "http.request", "body": b"ab", "more_body": False},
                        {"type": "http.disconnect"}]
    assert [m.get("body") for m in sent[1:]] == [b"first", b"last"]
    assert [m["more_body"] for m in sent[1:]] == [True, False]

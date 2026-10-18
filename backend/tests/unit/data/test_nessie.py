import httpx
import pytest

from app.adapters.nessie import NessieClient


def test_http_error_is_captured_without_credentials(caplog):
    key = "sentinel-private-key"

    def upstream(request):
        assert request.method == "GET"
        assert request.url.path == "/customers"
        assert request.url.params["key"] == key
        return httpx.Response(401, json={"message": str(request.url), "api_key": key})

    result = NessieClient(key, transport=httpx.MockTransport(upstream)).query(
        "customers.list", None)
    assert result["http_status"] == 401
    assert result["body_format"] == "json"
    assert key not in str(result)
    assert key not in caplog.text


@pytest.mark.parametrize("status,body", [(200, []), (404, "missing"), (500, "error"),
                                        (200, None)])
def test_status_and_body_are_preserved(status, body):
    transport = httpx.MockTransport(lambda r: httpx.Response(status, json=body)
                                    if body is not None else httpx.Response(200, content=b"null"))
    result = NessieClient("private", transport=transport).query("accounts.list", None)
    assert result["http_status"] == status
    assert result["response_body"] == body
    assert result["body_format"] == "json"


def test_timeout_has_no_invented_status_or_body():
    def timeout(request):
        raise httpx.ReadTimeout("private-key " + str(request.url))
    result = NessieClient("private-key", transport=httpx.MockTransport(timeout)).query(
        "accounts.list", None)
    assert result == {"http_status": None, "body_format": "none", "response_body": None,
                      "transport_error": {"type": "timeout", "message":
                                          "Nessie request did not receive a response."}}


def test_transport_rejects_nonallowlisted_paths():
    client = NessieClient("private")
    for method, path in [("GET", "https://example.com"), ("DELETE", "/customers"),
                         ("GET", "/accounts/../../customers"), ("POST", "/accounts")]:
        with pytest.raises(ValueError):
            client.request(method, path)


def test_hex_and_canonical_uuid_remote_ids_are_accepted():
    calls = []

    def upstream(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"_id": "01234567-89ab-cdef-0123-456789abcdef"})

    client = NessieClient("private", transport=httpx.MockTransport(upstream))
    client.query("accounts.get", "01234567-89ab-cdef-0123-456789abcdef")
    client.query("accounts.get", "a" * 24)
    with pytest.raises(ValueError):
        client.query("accounts.get", "01234567-89ab-cdef-0123-456789abcdeg")
    assert calls == ["/accounts/01234567-89ab-cdef-0123-456789abcdef", "/accounts/" + "a" * 24]

"""F1 regressions against the team-owned contract (no external services)."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from app.adapters.synthetic import load_transactions
from app.schemas.api import Alert, Analysis, FieldAction, MemorySummary
from app.schemas.transaction import Transaction


@pytest.fixture(scope="module")
def contract():
    root = Path(__file__).resolve().parents[3]
    return yaml.safe_load((root / "contracts/internal-api.openapi.yaml").read_text())


def validate(contract, schema, payload):
    Draft202012Validator(
        {**schema, "components": contract["components"]}, format_checker=FormatChecker(),
    ).validate(payload)


def assert_error(contract, response, status, code):
    assert response.status_code == status
    validate(contract, {"$ref": "#/components/schemas/ErrorEnvelope"}, response.json())
    assert response.json()["error"] == {
        "code": code,
        "message": ("Request does not match the API contract." if status == 422
                    else "Request could not be completed."),
        "request_id": response.headers["X-Request-ID"],
    }


def test_all_public_operations(contract, client):
    paths = contract["paths"]
    assert set(client.app.openapi()["paths"]) == set(paths)
    assert {(p, m) for p, item in client.app.openapi()["paths"].items() for m in item} == {
        (p, m) for p, item in paths.items() for m in item
    }
    memory_id = None
    for path, operation in paths.items():
        if "/admin/" in path:
            continue  # Admin request/response contracts are exercised below.
        method, spec = next(iter(operation.items()))
        url = path.replace("{transaction_id}", "txn_syn_004").replace(
            "{alert_id}", "alert_txn_syn_004").replace("{memory_id}", memory_id or "missing")
        kwargs = {}
        if path.endswith("/analyses"):
            kwargs["json"] = {"transaction_id": "txn_syn_004"}
        elif path.endswith("/confirmations"):
            kwargs["json"] = {"decision": "normal", "consent_to_memory": True}
        response = client.request(method, url, **kwargs)
        status = "204" if method == "delete" else "200"
        assert response.status_code == int(status)
        if status == "204":
            assert response.content == b""
            continue
        schema = spec["responses"][status]["content"]["application/json"]["schema"]
        validate(contract, schema, response.json())
        if path.endswith("/confirmations"):
            memory_id = response.json()["memory_id"]
        if path.endswith("/memories"):
            assert len(response.json()) == 1


@pytest.mark.parametrize("method,path,maximum", [
    ("get", "/api/v1/privacy/preview/{}", 80),
    ("post", "/api/v1/alerts/{}/confirmations", 80),
    ("delete", "/api/v1/memories/{}", 100),
])
@pytest.mark.parametrize("boundary", [1, 0, -1])
def test_path_id_bounds(contract, client, method, path, maximum, boundary):
    length = maximum + 1 if boundary == 1 else maximum if boundary == 0 else 1
    kwargs = {"json": {"decision": "normal", "consent_to_memory": False}} if method == "post" else {}
    response = client.request(method, path.format("x" * length), **kwargs)
    assert_error(contract, response, 422 if boundary == 1 else 404,
                 "invalid_request" if boundary == 1 else "not_found")
    # Empty path segments cannot match a route; verify minLength in generated parameters.
    template = next(p for p in client.app.openapi()["paths"]
                    if p.startswith(path.split("{}")[0]) and "{" in p)
    schema = client.app.openapi()["paths"][template][method]["parameters"][0]["schema"]
    assert schema["minLength"] == 1 and schema["maxLength"] == maximum


@pytest.mark.parametrize("value,status", [("x", 404), ("x" * 80, 404), ("", 422),
                                          ("x" * 81, 422), (123, 422), (None, 422)])
def test_analysis_id_bounds(contract, client, value, status):
    response = client.post("/api/v1/analyses", json={"transaction_id": value})
    assert_error(contract, response, status, "not_found" if status == 404 else "invalid_request")


@pytest.mark.parametrize("limit,count", [(None, 25), ("1", 1), ("100", 100)])
def test_limit_success(client, limit, count):
    tx = client.app.state.store.list_transactions(client.app.state.settings.demo_user_id)[0]
    store = client.app.state.store
    owner = client.app.state.settings.demo_user_id
    with store.connect() as db:
        db.execute("DELETE FROM demo_transactions WHERE owner=?", (owner,))
        db.execute("DELETE FROM demo_transaction_sets WHERE owner=?", (owner,))
    store.initialize_transactions(owner, [tx.model_copy(update={"id": f"txn_{i}"}) for i in range(101)])
    response = client.get("/api/v1/transactions", params={} if limit is None else {"limit": limit})
    assert response.status_code == 200
    assert len(response.json()) == count


@pytest.mark.parametrize("limit", ["0", "101", "-1", "1.5", "true", "invalid", ""])
def test_invalid_limit(contract, client, limit):
    assert_error(contract, client.get("/api/v1/transactions", params={"limit": limit}),
                 422, "invalid_request")


@pytest.mark.parametrize("body", [
    {}, {"decision": "normal"}, {"consent_to_memory": False},
    {"decision": "other", "consent_to_memory": False},
    {"decision": "normal", "consent_to_memory": False, "user_id": "private-marker"},
    *[{"decision": "normal", "consent_to_memory": value}
      for value in ["true", "false", "yes", 0, 1, None, [], {}]],
])
def test_confirmation_strict_body(contract, client, body):
    response = client.post("/api/v1/alerts/alert_txn_syn_004/confirmations", json=body)
    assert_error(contract, response, 422, "invalid_request")
    assert "private-marker" not in response.text
    assert client.app.state.store.status(client.app.state.settings.demo_user_id,
                                         "alert_txn_syn_004") == "open"
    assert client.get("/api/v1/memories").json() == []


@pytest.mark.parametrize("body", [{}, {"transaction_id": "txn_syn_004", "extra": "private-marker"}])
def test_analysis_strict_body(contract, client, body):
    response = client.post("/api/v1/analyses", json=body)
    assert_error(contract, response, 422, "invalid_request")
    assert "private-marker" not in response.text


def test_conflict_envelope(contract, client):
    path = "/api/v1/alerts/alert_txn_syn_004/confirmations"
    assert client.post(path, json={"decision": "normal", "consent_to_memory": False}).status_code == 200
    assert_error(contract, client.post(path, json={"decision": "review", "consent_to_memory": False}),
                 409, "confirmation_conflict")


@pytest.mark.parametrize("model", [Analysis, Alert])
@pytest.mark.parametrize("evidence,valid", [([], True), (["x" * 180] * 8, True),
                                          (["x" * 181], False), (["x"] * 9, False)])
def test_evidence_bounds(model, evidence, valid):
    data = dict(transaction_id="synthetic", alert_type="none", severity="low", needs_human=False,
                confidence=0, evidence=evidence, request_id="test")
    if model is Alert:
        data["alert_id"] = "alert_synthetic"
    if valid:
        assert model(**data).evidence == evidence
    else:
        with pytest.raises(ValidationError):
            model(**data)


@pytest.mark.parametrize("value", ["2026-10-17T12:00:00Z", "2026-10-17T12:00:00-04:00",
                                    datetime(2026, 10, 17, tzinfo=timezone(timedelta(hours=5)))])
def test_timezone_aware_transaction(contract, value):
    data = load_transactions()[0].model_dump()
    data["occurred_at"] = value
    tx = Transaction(**data)
    assert tx.occurred_at.utcoffset() is not None
    validate(contract, {"$ref": "#/components/schemas/Transaction"}, tx.model_dump(mode="json"))
    assert Transaction.model_validate_json(tx.model_dump_json()).occurred_at == tx.occurred_at


@pytest.mark.parametrize("value", ["2026-10-17T12:00:00", datetime(2026, 10, 17), "2026-10-17"])
def test_naive_transaction_rejected(value):
    data = load_transactions()[0].model_dump()
    data["occurred_at"] = value
    with pytest.raises(ValidationError):
        Transaction(**data)


def test_memory_timestamp_requires_timezone():
    with pytest.raises(ValidationError):
        MemorySummary(memory_id="mem", summary="Synthetic summary", source="local-fallback",
                      created_at="2026-10-17T12:00:00")


@pytest.mark.parametrize("output", [None, "bucket", 2, True, ["value"], {"value": 2}])
def test_field_action_unconstrained_json_output(contract, output):
    action = FieldAction(field="synthetic", action="allowed", reason="Test", output=output)
    validate(contract, {"$ref": "#/components/schemas/FieldAction"}, action.model_dump(mode="json"))
    assert action.output == output


def test_response_extra_fields_rejected(client):
    tx = load_transactions()[0].model_dump()
    with pytest.raises(ValidationError):
        Transaction(**tx, private_marker="private")
    response = client.post("/api/v1/analyses", json={"transaction_id": "txn_syn_004"})
    with pytest.raises(ValidationError):
        Analysis(**response.json(), private_marker="private")


def test_all_admin_operation_contracts(contract, client):
    import httpx
    from app.adapters.nessie import NessieClient
    from pydantic import SecretStr

    client.base_url = "http://127.0.0.1"
    client.headers["origin"] = "http://localhost:5173"
    client.app.state.settings.nessie_api_key = SecretStr("synthetic-test")
    def upstream(request):
        if request.url.path == '/customers':
            body = [{'_id': 'c' * 24}]
        elif request.url.path.endswith('/accounts'):
            body = [{'_id': 'a' * 24, 'customer_id': 'c' * 24, 'type': 'Checking', 'balance': 100, 'rewards': 0}]
        elif request.url.path.endswith('/purchases'):
            body = [{'_id': 'b' * 24, 'purchase_date': '2026-10-17T10:00:00+00:00',
                     'amount': 849, 'status': 'completed'}]
        else:
            body = []
        return httpx.Response(200, json=body)

    client.app.state.nessie = NessieClient('synthetic-test', transport=httpx.MockTransport(upstream))
    client.headers['content-type'] = 'application/json'
    prefix = "/api/v1/admin/nessie"
    operations = [
        ("post", "/query", {"query": "customers.list"}),
        ("get", "/resources", None),
        ("get", "/history", None),
        ("get", "/history/{history_id}", None),
        ("delete", "/history/{history_id}", {"confirm": True}),
        ("delete", "/history", {"confirm": True}),
        ('get', '/customers', None),
        ('post', '/customers/{customer_code}/workspace/refresh', {}),
        ('get', '/customers/{customer_code}/health', None),
        ('get', '/customers/{customer_code}/transactions', None),
        ('post', '/customers/{customer_code}/analyses', {'transaction_id': '{transaction_id}'}),
        ('get', '/customers/{customer_code}/alerts', None),
        ('get', '/customers/{customer_code}/privacy/preview/{transaction_id}', None),
        ('post', '/customers/{customer_code}/transactions/{transaction_id}/explanation', {}),
        ('post', '/customers/{customer_code}/alerts/{alert_id}/confirmations',
         {'decision': 'normal', 'consent_to_memory': True}),
        ('get', '/customers/{customer_code}/memories', None),
        ('delete', '/customers/{customer_code}/memories/{memory_id}', None),
        ('get', '/customers/{customer_code}/transactions/{transaction_id}/relevant-memories', None),
        ('get', '/customers/{customer_code}/memories/{memory_id}/deletion-verification', None),
    ]
    expected = {(p, m) for p, item in contract["paths"].items() if "/admin/" in p for m in item}
    assert {(prefix + path, method) for method, path, _ in operations} == expected
    history_id = None
    customer_code = transaction_id = memory_id = ''
    for method, path, body in operations:
        replacements = {'{history_id}': str(history_id), '{customer_code}': customer_code,
                        '{transaction_id}': transaction_id, '{alert_id}': 'alert_' + transaction_id,
                        '{memory_id}': memory_id}
        url = prefix + path
        payload = dict(body) if body is not None else None
        for placeholder, value in replacements.items():
            url = url.replace(placeholder, value)
            if payload:
                payload = {key: value if item == placeholder else item for key, item in payload.items()}
        kwargs = {'json': payload} if payload is not None else {}
        response = client.request(method, url, **kwargs)
        if path.endswith('/memories/{memory_id}'):
            assert response.status_code == 204 and not response.content
            continue
        assert response.status_code == 200, (path, response.text)
        schema = contract["paths"][prefix + path][method]["responses"]["200"]["content"]["application/json"]["schema"]
        validate(contract, schema, response.json())
        if path == "/query":
            history_id = response.json()["history_id"]
            assert history_id is not None
            customer_code = response.json()['response_body'][0]['resource_id']
        if path.endswith('/workspace/refresh'):
            transaction_id = response.json()['transactions'][0]['id']
        if path.endswith('/confirmations'):
            memory_id = response.json()['memory_id']


def test_all_contract_references_resolve(contract):
    def visit(value):
        if isinstance(value, dict):
            if '$ref' in value:
                target = contract
                for part in value['$ref'].removeprefix('#/').split('/'):
                    target = target[part.replace('~1', '/').replace('~0', '~')]
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(contract)

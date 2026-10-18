import asyncio
import json

import httpx
import pytest

from app.adapters.synthetic import load_transactions
from app.services.ai.decision import review
from app.services.ai.jev_client import JevCallError, classify, parse_response, request_body
from app.services.ai.privacy import safe_payload


def severity(score=1.89):
    return {"type": "score", "score": score, "legend": {"0": "Low", "1": "Medium", "2": "High"}}


def test_fractional_score_and_invalid_score_boundary():
    system = {"model": "jev-1.13.0", "answers": {
        "pattern": {"type": "choice", "choice": "none", "confidence": 0.8},
        "needs_review": {"type": "noul", "noul": 0.4}, "severity": severity()}}
    assert parse_response({"system_one": system}).severity_score == 1.89
    for value in (True, -1, 2.1, [], 10 ** 400):
        system["answers"]["severity"] = severity(value)
        with pytest.raises(JevCallError):
            parse_response({"system_one": system})


@pytest.mark.parametrize("field,value", [
    ("choice", []), ("choice", {}), ("model", "x" * 81), ("model", "jev-2.0.0"), ("confidence", 10 ** 400),
])
def test_malformed_success_always_falls_back_to_rules(field, value):
    rows, tx, _ = _rows()
    system = {"model": "jev-1.13.0", "answers": {
        "pattern": {"type": "choice", "choice": "duplicate", "confidence": 0.8},
        "needs_review": {"type": "noul", "noul": 0.9}, "severity": severity()}}
    if field == "model":
        system[field] = value
    else:
        system["answers"]["pattern"][field] = value

    async def run():
        transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"system_one": system}))
        async with httpx.AsyncClient(transport=transport) as client:
            return await review(tx, rows, "req", "unknown", "synthetic-key", client=client)

    result = asyncio.run(run())
    assert result.provider_mode == "degraded"
    assert result.alert_type == "duplicate" and result.needs_human
    assert result.model_version is None


def test_uncertain_model_answer_still_requires_a_person():
    rows, _, _ = _rows()
    tx = rows[0]

    async def run():
        transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"system_one": {
            "model": "jev-1.13.0", "answers": {
                "pattern": {"type": "choice", "choice": "none", "confidence": 0.8},
                "needs_review": {"type": "noul", "noul": 0.4}, "severity": severity()}}}))
        async with httpx.AsyncClient(transport=transport) as client:
            return await review(tx, rows, "req", "unknown", "synthetic-key",
                                client=client, force_live=True)

    assert asyncio.run(run()).needs_human is True


def _rows():
    rows = load_transactions()
    tx = next(row for row in rows if row.id == "txn_syn_004")
    nasty = tx.model_copy(update={
        "merchant_display": "PRIVATE PERSON 123 Main St",
        "id": "txn_secret_999",
        "account_token": "acct_secret_999",
    })
    return rows, tx, nasty


def test_request_uses_backboard_system_one_and_drops_raw_fields():
    rows, _tx, nasty = _rows()
    payload = safe_payload(nasty, rows)
    body = request_body(payload)
    text = json.dumps(body)
    assert body["llm_provider"] == "typesafe"
    assert body["model_name"] == "jev-latest"
    assert body["stream"] is False
    assert "thread_id" not in body
    assert body["memory"] == "off"
    assert set(body["system_one"]["state"]) == set(payload.model_dump())
    for forbidden in (nasty.id, nasty.account_token, nasty.merchant_display, "11.99", "StreamWave"):
        assert forbidden not in text


def test_parser_accepts_system_one_answers_and_rejects_unknown_choice():
    parsed = parse_response({
        "status": "COMPLETED",
        "system_one": {
            "model": "jev-1.13.0",
            "answers": {
                "pattern": {"type": "choice", "choice": "duplicate", "confidence": 0.82},
                "needs_review": {"type": "noul", "noul": 0.91},
                "severity": severity(),
            },
        },
    })
    assert parsed.pattern == "duplicate"
    assert parsed.model_version == "jev-1.13.0"
    try:
        parse_response({
            "status": "COMPLETED",
            "system_one": {
                "model": "jev-1.13.0",
                "answers": {
                    "pattern": {"type": "choice", "choice": "fraud", "confidence": 0.99},
                    "needs_review": {"type": "noul", "noul": 0.5},
                "severity": severity(),
                },
            },
        })
    except JevCallError as exc:
        assert str(exc) == "invalid_response"
    else:
        raise AssertionError("unknown choice was accepted")


def test_http_failure_stays_on_rules_and_success_is_labeled_live():
    rows, tx, nasty = _rows()
    payload = safe_payload(nasty, rows)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/threads/messages"
        assert request.headers["X-API-Key"] == "synthetic-test-key"
        assert b"synthetic-test-key" not in request.content
        assert b"PRIVATE PERSON" not in request.content
        return httpx.Response(503, json={"message": "unavailable"})

    async def failed():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            try:
                await classify(payload, "synthetic-test-key", client=client)
            except JevCallError as exc:
                assert str(exc) == "request_failed"
            else:
                raise AssertionError("provider failure was treated as success")
            result = await review(tx, rows, "req", "unknown", "synthetic-test-key", client=client)
        return result

    degraded = asyncio.run(failed())
    assert degraded.provider_mode == "degraded"
    assert degraded.alert_type == "duplicate"
    assert degraded.model_version is None
    assert all("Jev via Backboard" not in line for line in degraded.evidence)

    async def succeeded():
        def ok(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "status": "COMPLETED",
                "system_one": {
                    "model": "jev-1.13.0",
                    "answers": {
                        "pattern": {"type": "choice", "choice": "none", "confidence": 0.4},
                        "needs_review": {"type": "noul", "noul": 0.2},
                "severity": severity(),
                    },
                },
            })

        async with httpx.AsyncClient(transport=httpx.MockTransport(ok)) as client:
            return await review(tx, rows, "req", "normal", "synthetic-test-key", client=client)

    live = asyncio.run(succeeded())
    assert live.provider_mode == "rules+jev-live"
    assert live.alert_type == "duplicate" and live.needs_human
    assert live.model_version == "jev-1.13.0"
    assert live.confidence == 1.0
    assert any("Jev via Backboard: none" in line for line in live.evidence)


def test_missing_key_does_not_call_the_provider():
    rows, tx, _nasty = _rows()

    async def run():
        return await review(tx, rows, "req", "unknown", "  ")

    result = asyncio.run(run())
    assert result.provider_mode == "rules-only"
    assert result.alert_type == "duplicate"

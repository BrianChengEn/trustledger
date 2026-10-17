import copy
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.services.nessie_console import compare_snapshots

FIXTURES = Path(__file__).resolve().parents[3] / "datasets/nessie/history.json"


def test_seven_fixture_comparisons():
    history = json.loads(FIXTURES.read_text())
    rows = {r["id"]: r for r in history["records"]}
    for case in history["comparisons"]:
        left = rows[case["left_id"]]
        right = rows[case["right_id"]]
        result = compare_snapshots(left, right)
        if case["id"] in {"CMP004", "CMP005"}:
            assert result["data_changed"] is False
        else:
            assert result["data_changed"] is True
        if case["id"] == "CMP006":
            assert result["status_change"] == {"before": 200, "after": 404}
        expected = case["expected"]
        changed_fields = {c["path"].split("/")[-1] for c in result["changes"]}
        if "changed_fields" in expected:
            assert set(expected["changed_fields"]) <= changed_fields


def snapshot(body):
    return {"query": "accounts.get", "resource_id": "a" * 24, "source": "synthetic",
            "http_status": 200, "transport_error": None, "body_format": "json",
            "response_body": body}


def test_presence_pointers_and_business_dates():
    left = snapshot({"a/b~": None, "transaction_date": "2026-10-01"})
    right = snapshot({"added": None, "transaction_date": "2026-10-02"})
    result = compare_snapshots(left, right)
    changes = {c["path"]: c for c in result["changes"]}
    assert changes["/a~1b~0"]["before_present"] is True
    assert changes["/a~1b~0"]["after_present"] is False
    assert changes["/added"]["before_present"] is False
    assert changes["/added"]["after_present"] is True
    assert changes["/transaction_date"]["kind"] == "changed"


def test_incompatible_and_unmatchable_collections():
    left = snapshot([])
    for field, value in [("source", "nessie"), ("query", "accounts.list"),
                         ("resource_id", "b" * 24)]:
        right = {**left, field: value}
        with pytest.raises(HTTPException) as exc:
            compare_snapshots(left, right)
        assert exc.value.status_code == 409
    for body in [[{}], [{"_id": "same"}, {"_id": "same"}]]:
        with pytest.raises(HTTPException):
            compare_snapshots(left, snapshot(body))
    before = snapshot({"value": 1, "array": [False]})
    after = snapshot({"value": True, "array": [0]})
    original = copy.deepcopy(before)
    assert len(compare_snapshots(before, after)["changes"]) == 2
    assert before == original

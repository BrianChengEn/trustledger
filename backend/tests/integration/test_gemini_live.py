"""Opt-in live Gemini check. scripts/check.sh does not set GEMINI_LIVE_TEST."""
import os

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

pytestmark = pytest.mark.live_network


def test_two_synthetic_explanations_against_gemini(tmp_path):
    if os.environ.get("GEMINI_LIVE_TEST") != "1":
        pytest.skip("Set GEMINI_LIVE_TEST=1 to call Gemini. This is not part of check.sh.")
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        pytest.skip("GEMINI_API_KEY is not set.")
    settings = Settings(
        _env_file=None, database_path=tmp_path / "live.db", allow_memory_write=True,
        gemini_api_key=key, backboard_api_key="", jev_api_key="", nessie_api_key="",
    )
    with TestClient(create_app(settings)) as client:
        # At most two calls. Stop on authentication, quota, or a provider failure.
        for transaction_id in ("txn_syn_004", "txn_syn_001"):
            response = client.post(f"/api/v1/transactions/{transaction_id}/explanation")
            assert key not in response.text
            assert response.status_code == 200
            body = response.json()
            if body["explanation_mode"] != "gemini-live":
                pytest.fail(f"stopped: mode={body['explanation_mode']} failure={body['failure']}")
            assert body["sent_to_provider"] is True
            assert body["model_version"] == settings.gemini_model
            assert "StreamWave" not in json_text(body) and "Campus Coffee" not in json_text(body)
            assert "acct_demo" not in json_text(body["shared"])


def json_text(body) -> str:
    import json
    return json.dumps(body)

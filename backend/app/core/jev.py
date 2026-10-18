"""Explicit Backboard/Jev adapter. No model score is mapped to a risk decision."""
import asyncio
import re

import httpx
from pydantic import SecretStr, ValidationError

from app.core.fraud import (
    FraudAssessment, FraudFeatures, FraudHTTPError, FraudTimeout, FraudUnavailable,
    MalformedAssessment, ProviderMetadata, validated_features,
)
from app.services.ai.jev_client import JevCallError, JevClassification, classify

# Total inference deadline, including connection and body read; no inline retries.
INFERENCE_TIMEOUT = 3.0


class BackboardJevProvider:
    def __init__(self, api_key: SecretStr, transport: httpx.AsyncBaseTransport | None = None):
        self._api_key = api_key
        self._transport = transport

    def assess(self, features: FraudFeatures) -> FraudAssessment:
        features = validated_features(features)
        key = self._api_key.get_secret_value().strip()
        if not key:
            raise FraudUnavailable()
        # FastAPI's synchronous analysis route executes in a worker thread. Do not
        # reuse event loops/clients across requests or call this from an async route.
        try:
            return asyncio.run(self._assess(features, key))
        except TimeoutError:
            raise FraudTimeout() from None
        except JevCallError as exc:
            if str(exc) in {"invalid_response", "incomplete_response", "unsafe_state"}:
                raise MalformedAssessment() from None
            raise FraudUnavailable() from None
        except (ValidationError, TypeError, ValueError):
            raise MalformedAssessment() from None
        except httpx.HTTPError:
            raise FraudUnavailable() from None

    async def _assess(self, features: FraudFeatures, key: str) -> FraudAssessment:
        async def status(response: httpx.Response):
            code = response.status_code
            if code in {401, 402, 429} or 500 <= code <= 599:
                raise FraudHTTPError(code)
            if code != 200:
                raise FraudUnavailable()

        async with asyncio.timeout(INFERENCE_TIMEOUT):
            async with httpx.AsyncClient(
                transport=self._transport, timeout=None, follow_redirects=False,
                event_hooks={"response": [status]},
            ) as client:
                value = await classify(features, key, client=client)
            # Revalidate even injected/constructed results; suppress raw-value warnings.
            result = JevClassification.model_validate(value.model_dump(warnings=False))
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", result.model_version):
                raise MalformedAssessment()
            return FraudAssessment(
                alert_type=result.pattern, severity=None, needs_human=None, evidence=[],
                metadata=ProviderMetadata(name="jev", mode="external", model_version=result.model_version),
                # needs_review and choice_confidence have no approved decision mapping.
                # Neither is promoted to confidence, probability or a boolean threshold.
            )

"""AI owner: implement verified Jev client here. Never pass raw transactions."""
from app.schemas.api import SafePayload


def decide(payload: SafePayload):
    raise NotImplementedError("Jev live integration is not enabled in this synthetic starter.")

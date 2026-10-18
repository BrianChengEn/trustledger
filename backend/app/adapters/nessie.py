"""Allowlisted sandbox transport; the transaction dashboard remains synthetic."""

import logging
import re
from urllib.parse import quote, quote_plus

import httpx

API_BASE = "https://prod-api.nessieisreal.com"
QUERIES = {
    "customers.list": "/customers",
    "accounts.list": "/accounts",
    "accounts.get": "/accounts/{id}",
    "accounts.by_customer": "/customers/{id}/accounts",
    "deposits.by_account": "/accounts/{id}/deposits",
    "withdrawals.by_account": "/accounts/{id}/withdrawals",
}
REMOTE_ID = re.compile(r"(?:[0-9a-f]{24}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
                       r"[0-9a-f]{4}-[0-9a-f]{12})")


def sanitize(value, key):
    if isinstance(value, dict):
        return {sanitize(k, key): sanitize(v, key) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(v, key) for v in value]
    if isinstance(value, str):
        for secret in {key, quote(key, safe=""), quote_plus(key)} - {""}:
            value = value.replace(secret, "[REDACTED]")
        return re.sub(r"([?&]key=)[^&\s\"'<>]+", r"\1[REDACTED]", value,
                      flags=re.IGNORECASE)
    return value


class NessieClient:
    def __init__(self, key, *, transport=None):
        self.key = key
        self.transport = transport
        # HTTP client debug output includes credential-bearing request targets.
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)

    def request(self, method, path, payload=None):
        allowed = (r"/(customers|accounts)" if method == "GET" else r"/customers")
        allowed += rf"|/customers/{REMOTE_ID.pattern}/accounts"
        allowed += rf"|/accounts/{REMOTE_ID.pattern}/(?:deposits|withdrawals)"
        if method == "GET":
            allowed += rf"|/accounts/{REMOTE_ID.pattern}"
        if method not in {"GET", "POST"} or not re.fullmatch(allowed, path):
            raise ValueError("Unsupported Nessie operation")
        if not self.key:
            raise NessieNotConfigured("Nessie configuration is unavailable.")
        try:
            with httpx.Client(base_url=API_BASE, timeout=15, follow_redirects=False,
                              transport=self.transport) as client:
                response = client.request(method, path, params={"key": self.key}, json=payload)
            try:
                body, body_format = response.json(), "json"
            except ValueError:
                body, body_format = response.text, "text"
            return {"http_status": response.status_code, "body_format": body_format,
                    "response_body": sanitize(body, self.key), "transport_error": None}
        except httpx.TransportError as exc:
            category = "timeout" if isinstance(exc, httpx.TimeoutException) else "connection"
            return {"http_status": None, "body_format": "none", "response_body": None,
                    "transport_error": {"type": category,
                                        "message": "Nessie request did not receive a response."}}

    def query(self, query, resource_id):
        path = QUERIES[query]
        if "{id}" in path:
            if not isinstance(resource_id, str) or not REMOTE_ID.fullmatch(resource_id):
                raise ValueError("Invalid resource ID")
            path = path.format(id=resource_id)
        elif resource_id:
            raise ValueError("Unexpected resource ID")
        return self.request("GET", path)


class NessieNotConfigured(RuntimeError):
    pass


def load_transactions():
    raise NessieNotConfigured("Live Nessie adapter is not implemented; use synthetic adapter.")

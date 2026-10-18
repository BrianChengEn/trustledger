"""Fail closed before starting the restricted, no-provider release."""
from pathlib import Path
from urllib.parse import urlsplit

from app.core.config import Settings

settings = Settings(_env_file=None)
checks = [
    settings.require_login,
    settings.transaction_provider == 'synthetic',
    settings.fraud_provider == 'rules-only',
    not settings.allow_demo_edit,
    not settings.demo_admin_passcode.get_secret_value(),
    len(settings.session_secret.get_secret_value()) >= 64,
    len(settings.demo_user_passcode.get_secret_value()) >= 16,
    urlsplit(settings.frontend_origin).scheme == 'https',
    'REPLACE' not in settings.frontend_origin,
    settings.database_path == Path('/var/lib/trustledger/trustledger-demo.db'),
    settings.source_database_dir == Path('/var/lib/trustledger/sources'),
]
for secret in (settings.session_secret, settings.demo_user_passcode):
    checks.append('REPLACE' not in secret.get_secret_value())
for secret in (settings.gemini_api_key, settings.backboard_api_key,
               settings.nessie_api_key, settings.jev_api_key):
    checks.append(not secret.get_secret_value())
if not all(checks):
    raise SystemExit('Restricted demo configuration rejected; review runtime settings privately.')

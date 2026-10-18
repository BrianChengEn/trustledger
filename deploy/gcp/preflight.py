"""Fail closed before starting the authenticated, Nessie-only GCP release."""
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import ValidationError

from app.core.config import Settings


def validate(settings: Settings) -> None:
    checks = [
        settings.app_env == 'production',
        settings.require_login,
        settings.transaction_provider == 'nessie',
        bool(settings.nessie_api_key.get_secret_value().strip()),
        bool(settings.nessie_customer_id.get_secret_value()),
        settings.demo_account_token is None,
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
    for secret in (settings.session_secret, settings.demo_user_passcode,
                   settings.nessie_api_key, settings.nessie_customer_id):
        checks.append('REPLACE' not in secret.get_secret_value())
    for secret in (settings.gemini_api_key, settings.backboard_api_key, settings.jev_api_key):
        checks.append(not secret.get_secret_value())
    if not all(checks):
        raise SystemExit('GCP production configuration rejected; review runtime settings privately.')


if __name__ == '__main__':
    try:
        validate(Settings(_env_file=None))
    except ValidationError:
        # Pydantic errors may include raw settings input; never log production secrets.
        raise SystemExit('GCP production configuration invalid; review runtime settings privately.') from None

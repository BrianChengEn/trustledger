"""Production gate rejects unsafe settings without leaking credentials."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.core.config import Settings

PREFLIGHT = Path(__file__).resolve().parents[4] / 'deploy/gcp/preflight.py'
spec = importlib.util.spec_from_file_location('gcp_preflight', PREFLIGHT)
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


def configured(**overrides):
    values = dict(app_env='production', transaction_provider='nessie', require_login=True,
                  nessie_api_key='sandbox-test-key', nessie_customer_id='a' * 24,
                  fraud_provider='rules-only', allow_demo_edit=False,
                  session_secret='s' * 64, demo_user_passcode='p' * 24,
                  demo_admin_passcode='', frontend_origin='https://35.227.39.10',
                  database_path='/var/lib/trustledger/trustledger-demo.db',
                  source_database_dir='/var/lib/trustledger/sources',
                  gemini_api_key='', backboard_api_key='', jev_api_key='')
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_accepts_explicit_production_nessie_selection():
    preflight.validate(configured())


@pytest.mark.parametrize('override', [
    {'app_env': 'test'}, {'app_env': 'test', 'transaction_provider': 'synthetic'},
    {'require_login': False}, {'nessie_api_key': ''}, {'nessie_customer_id': ''},
    {'nessie_api_key': 'REPLACE_WITH_AUTHORIZED_SANDBOX_KEY'},
    {'demo_account_token': 'acct_' + 'b' * 32}, {'fraud_provider': 'mock-jev'},
    {'allow_demo_edit': True}, {'demo_admin_passcode': 'admin'},
    {'session_secret': 'short'}, {'demo_user_passcode': ''},
    {'frontend_origin': 'http://35.227.39.10'}, {'database_path': '/tmp/demo.db'},
    {'source_database_dir': '/tmp/sources'}, {'gemini_api_key': 'disabled'},
    {'backboard_api_key': 'disabled'}, {'jev_api_key': 'disabled'},
])
def test_rejects_unsafe_release_settings(override):
    with pytest.raises(SystemExit, match='configuration rejected'):
        preflight.validate(configured(**override))


def test_invalid_settings_do_not_print_credentials():
    env = {**os.environ, 'PYTHONPATH': str(PREFLIGHT.parents[2] / 'backend'),
           'APP_ENV': 'production', 'TRANSACTION_PROVIDER': 'nessie',
           'NESSIE_API_KEY': 'never-log-this-secret',
           'NESSIE_CUSTOMER_ID': 'private-invalid-selection'}
    result = subprocess.run([sys.executable, str(PREFLIGHT)], env=env,
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert 'configuration invalid' in result.stderr
    assert 'never-log-this-secret' not in result.stderr
    assert 'private-invalid-selection' not in result.stderr
    assert 'Traceback' not in result.stderr

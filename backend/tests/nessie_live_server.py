"""Explicit opt-in local browser harness; actual Nessie GETs, isolated app persistence."""
import os

import uvicorn

from app.adapters.nessie import NessieClient
from app.core.config import Settings
from app.main import create_app

if os.environ.get('NESSIE_LIVE_TEST') != '1' or not os.environ.get('NESSIE_LOCAL_PASSCODE'):
    raise RuntimeError('Explicit live verification configuration required')
settings = Settings(transaction_provider='nessie', app_env='development',
                    demo_user_id='isolated-nessie-browser-verification', require_login=True,
                    demo_user_passcode=os.environ['NESSIE_LOCAL_PASSCODE'], demo_admin_passcode='',
                    fraud_provider='rules-only', backboard_api_key='', gemini_api_key='', jev_api_key='',
                    allow_memory_write=False, allow_demo_edit=False)
if not settings.nessie_customer_id.get_secret_value():
    raise RuntimeError('Local sandbox customer selection required')


class ReadOnlyVerificationClient(NessieClient):
    calls = 0

    def request(self, method, path, payload=None):
        if method != 'GET' or self.calls >= 150:
            raise RuntimeError('Read-only verification request budget exceeded')
        self.calls += 1
        return super().request(method, path, payload)


app = create_app(settings)
app.state.nessie = ReadOnlyVerificationClient(settings.nessie_api_key.get_secret_value())
if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=int(os.environ['NESSIE_LOCAL_PORT']), log_level='warning', access_log=False)

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings
from app.main import create_app


def test_blank_login_roles_and_configured_passcode(tmp_path):
    settings = Settings(_env_file=None, database_path=tmp_path / 'login.db', require_login=True,
                        backboard_api_key='', nessie_api_key='', jev_api_key='')
    with TestClient(create_app(settings), base_url='http://127.0.0.1') as client:
        client.headers['origin'] = 'http://127.0.0.1:5176'
        assert client.get('/api/v1/transactions').status_code == 401
        for role in ('user', 'admin'):
            response = client.post('/api/v1/auth/login', json={'role': role, 'passcode': ''})
            assert response.status_code == 200
            assert response.json()['role'] == role
            assert 'httponly' in response.headers['set-cookie'].lower()
            assert client.get('/api/v1/transactions').status_code == 200
            if role == 'user':
                assert client.get('/api/v1/admin/nessie/history').status_code == 403
            else:
                assert client.get('/api/v1/admin/nessie/history').status_code == 503
            assert client.post('/api/v1/auth/logout', json={}).status_code == 200
            assert client.get('/api/v1/transactions').status_code == 401
        settings.demo_admin_passcode = SecretStr('configured-pass')
        assert client.post('/api/v1/auth/login', json={'role': 'admin', 'passcode': ''}).status_code == 401
        assert client.post('/api/v1/auth/login', json={'role': 'admin', 'passcode': 'configured-pass'}).status_code == 200
        client.cookies.clear()
        client.cookies.set('tl_session', 'forged')
        assert client.get('/api/v1/transactions').status_code == 401

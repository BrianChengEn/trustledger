import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def test_account_demo_launcher_isolates_test_state_and_never_calls_a_vendor(tmp_path):
    root = Path(__file__).resolve().parents[4]
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    launcher = scripts / 'dev-account-demo-backend.sh'
    shutil.copyfile(root / 'scripts/dev-account-demo-backend.sh', launcher)
    python = tmp_path / 'backend/.venv/bin/python'
    python.parent.mkdir(parents=True)
    keys = ['APP_ENV', 'DATABASE_PATH', 'TRANSACTION_PROVIDER', 'NESSIE_API_KEY',
            'BACKBOARD_API_KEY', 'GEMINI_API_KEY', 'JEV_API_KEY', 'ALLOW_DEMO_EDIT',
            'NESSIE_LIVE_TEST', 'FRONTEND_ORIGIN']
    python.write_text(f'#!{sys.executable}\nimport json, os, sys\n'
                      f'print(json.dumps({{"env": {{k: os.environ.get(k) for k in {keys!r}}}, '
                      '"args": sys.argv[1:]}))\n')
    python.chmod(0o755)
    env = {**os.environ, 'APP_ENV': 'production', 'DATABASE_PATH': '/unused/product.db',
           'DEMO_ACCOUNT_TOKEN': 'acct_' + 'a' * 32, 'NESSIE_LIVE_TEST': '1',
           **{key: 'sentinel-not-a-secret' for key in (
               'NESSIE_API_KEY', 'BACKBOARD_API_KEY', 'GEMINI_API_KEY', 'JEV_API_KEY')}}
    result = subprocess.run(['bash', str(launcher)], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    captured = json.loads(result.stdout.splitlines()[-1])
    assert captured['env']['APP_ENV'] == 'test'
    assert captured['env']['DATABASE_PATH'] == str(tmp_path / 'backend/data/account-demo-test.db')
    assert captured['env']['TRANSACTION_PROVIDER'] == 'account-demo'
    assert captured['env']['ALLOW_DEMO_EDIT'] == 'false'
    assert captured['env']['NESSIE_LIVE_TEST'] == '0'
    assert captured['env']['FRONTEND_ORIGIN'] == 'http://127.0.0.1:5174'
    assert all(captured['env'][key] == '' for key in (
        'NESSIE_API_KEY', 'BACKBOARD_API_KEY', 'GEMINI_API_KEY', 'JEV_API_KEY'))
    assert captured['args'] == ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1',
                                '--port', '8002', '--no-access-log']
    assert 'not live Nessie' in result.stdout
    assert not (tmp_path / 'backend/data').exists()

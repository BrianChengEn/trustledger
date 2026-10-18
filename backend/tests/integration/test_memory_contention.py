"""Optional memory context must not prevent the management view from loading."""
import sqlite3
from threading import Timer

import pytest


def test_memory_list_survives_short_context_lock_contention(client):
    confirmed = client.post('/api/v1/alerts/alert_txn_syn_004/confirmations',
                            json={'decision': 'normal', 'consent_to_memory': True})
    assert confirmed.status_code == 200
    before = client.get('/api/v1/memories').json()
    assert len(before) == 1
    blocker = sqlite3.connect(client.app.state.store.filename, check_same_thread=False)
    blocker.execute('BEGIN EXCLUSIVE')
    release = Timer(0.5, blocker.rollback)
    release.start()
    try:
        with pytest.raises(sqlite3.OperationalError):
            client.app.state.store.consented_memory_summaries(client.app.state.settings.demo_user_id)
        response = client.get('/api/v1/memories')
    finally:
        release.cancel()
        release.join()
        blocker.rollback()
        blocker.close()
    assert response.status_code == 200
    assert response.json() == before
    assert client.get('/api/v1/health').json()['memory_mode'] == 'local-fallback'

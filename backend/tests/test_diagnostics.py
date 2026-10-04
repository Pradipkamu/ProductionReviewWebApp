from pathlib import Path

from fastapi.testclient import TestClient

from app.api import diagnostics as diagnostics_api
from app.main import app


def _headers(client):
    response = client.post('/api/auth/login', json={'username': 'admin', 'password': 'ChangeMe123!'})
    return {'Authorization': 'Bearer ' + response.json()['access_token']}


def test_diagnostics_reports_database_storage_and_backup(tmp_path):
    imports = tmp_path / 'imports'; attachments = tmp_path / 'attachments'; backups = tmp_path / 'backups'
    for path in (imports, attachments, backups):
        path.mkdir()
    backup = backups / 'pms_before_update.dump'; backup.write_bytes(b'not-empty')
    Path(str(backup) + '.sha256').write_text('test checksum', encoding='utf-8')
    previous = (diagnostics_api.settings.upload_dir, diagnostics_api.settings.attachments_dir, diagnostics_api.settings.backup_dir)
    diagnostics_api.settings.upload_dir = str(imports)
    diagnostics_api.settings.attachments_dir = str(attachments)
    diagnostics_api.settings.backup_dir = str(backups)
    try:
        client = TestClient(app)
        response = client.get('/api/diagnostics', headers=_headers(client))
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['status'] == 'ok'
        assert result['backend']['version'] == '0.5.3'
        assert result['database']['status'] == 'ok'
        assert result['backup']['file_name'] == backup.name
        assert all(row['writable'] for row in result['storage'])
    finally:
        diagnostics_api.settings.upload_dir, diagnostics_api.settings.attachments_dir, diagnostics_api.settings.backup_dir = previous


def test_diagnostics_requires_login():
    assert TestClient(app).get('/api/diagnostics').status_code == 401

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.api import diagnostics as diagnostics_api
from app.main import app


def _headers(client):
    response = client.post('/api/auth/login', json={'username': 'admin', 'password': 'ChangeMe123!'})
    return {'Authorization': 'Bearer ' + response.json()['access_token']}


def test_diagnostics_reports_database_storage_backup_restore_and_security(tmp_path):
    imports = tmp_path / 'imports'; attachments = tmp_path / 'attachments'; backups = tmp_path / 'backups'
    for path in (imports, attachments, backups):
        path.mkdir()
    backup = backups / 'pms_before_update.dump'; backup.write_bytes(b'not-empty')
    digest = hashlib.sha256(backup.read_bytes()).hexdigest()
    Path(str(backup) + '.sha256').write_text(digest + '\n', encoding='utf-8')
    (backups / 'restore_verification.json').write_text(json.dumps({
        'status':'ok',
        'verified_at':datetime.now(timezone.utc).isoformat(),
        'backup_file':backup.name,
        'backup_sha256':digest,
        'schema_version':'0010_security_sessions',
        'core_tables':'OK',
    }), encoding='utf-8')

    previous = (
        diagnostics_api.settings.upload_dir,
        diagnostics_api.settings.attachments_dir,
        diagnostics_api.settings.backup_dir,
        diagnostics_api.settings.admin_password,
    )
    diagnostics_api.settings.upload_dir = str(imports)
    diagnostics_api.settings.attachments_dir = str(attachments)
    diagnostics_api.settings.backup_dir = str(backups)
    diagnostics_api.settings.admin_password = 'NonDefaultBootstrapPassword123!'
    try:
        client = TestClient(app)
        response = client.get('/api/diagnostics', headers=_headers(client))
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['status'] == 'ok'
        assert result['backend']['version'] == '0.5.5'
        assert result['database']['status'] == 'ok'
        assert result['backup']['file_name'] == backup.name
        assert result['backup']['checksum_valid'] is True
        assert result['restore_verification']['status'] == 'ok'
        assert result['security']['status'] == 'ok'
        assert '.pdf' in result['uploads']['allowed_attachment_extensions']
        assert all(row['writable'] for row in result['storage'])
    finally:
        (
            diagnostics_api.settings.upload_dir,
            diagnostics_api.settings.attachments_dir,
            diagnostics_api.settings.backup_dir,
            diagnostics_api.settings.admin_password,
        ) = previous


def test_diagnostics_flags_backup_checksum_mismatch(tmp_path):
    backups=tmp_path/'backups';imports=tmp_path/'imports';attachments=tmp_path/'attachments'
    for p in (backups,imports,attachments):p.mkdir()
    backup=backups/'bad.dump';backup.write_bytes(b'backup-data')
    Path(str(backup)+'.sha256').write_text('0'*64,encoding='utf-8')
    previous=(diagnostics_api.settings.upload_dir,diagnostics_api.settings.attachments_dir,diagnostics_api.settings.backup_dir)
    diagnostics_api.settings.upload_dir=str(imports);diagnostics_api.settings.attachments_dir=str(attachments);diagnostics_api.settings.backup_dir=str(backups)
    try:
        c=TestClient(app);result=c.get('/api/diagnostics',headers=_headers(c)).json()
        assert result['backup']['status']=='error'
        assert result['backup']['checksum_valid'] is False
    finally:
        diagnostics_api.settings.upload_dir,diagnostics_api.settings.attachments_dir,diagnostics_api.settings.backup_dir=previous


def test_diagnostics_requires_login():
    assert TestClient(app).get('/api/diagnostics').status_code == 401

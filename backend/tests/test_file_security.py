import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import app
from app.api import import_preview as import_preview_api

from app.services.file_security import (
    UploadSecurityError,
    safe_path,
    save_limited_stream,
    validate_attachment_file,
    validate_workbook_file,
)


def test_valid_workbook_and_safe_attachment_types(tmp_path):
    workbook=tmp_path/'valid.xlsx'
    wb=Workbook();wb.active['A1']='Plan';wb.save(workbook)
    validate_workbook_file(workbook,'valid.xlsx',128*1024*1024)
    mime=validate_attachment_file(workbook,'evidence.xlsx',{'.xlsx'},128*1024*1024)
    assert 'spreadsheetml' in mime

    pdf=tmp_path/'evidence.pdf';pdf.write_bytes(b'%PDF-1.7\nminimal-test\n%%EOF')
    assert validate_attachment_file(pdf,'evidence.pdf',{'.pdf'},128*1024*1024)=='application/pdf'


def test_rejects_fake_office_executable_and_path_escape(tmp_path):
    fake=tmp_path/'fake.xlsx';fake.write_bytes(b'not-a-zip')
    with pytest.raises(UploadSecurityError):
        validate_workbook_file(fake,'fake.xlsx',128*1024*1024)

    exe=tmp_path/'tool.exe';exe.write_bytes(b'MZ'+b'0'*100)
    with pytest.raises(UploadSecurityError):
        validate_attachment_file(exe,'tool.exe',{'.pdf','.xlsx'},128*1024*1024)

    with pytest.raises(UploadSecurityError):
        safe_path(tmp_path,'../outside.txt')


def test_rejects_mismatched_attachment_signature(tmp_path):
    disguised=tmp_path/'photo.png';disguised.write_bytes(b'<html>not an image</html>')
    with pytest.raises(UploadSecurityError):
        validate_attachment_file(disguised,'photo.png',{'.png'},128*1024*1024)


def test_limited_stream_removes_partial_file(tmp_path):
    target=tmp_path/'too-large.bin'
    with pytest.raises(UploadSecurityError) as exc:
        save_limited_stream(io.BytesIO(b'x'*1025),target,1024)
    assert exc.value.status_code==413
    assert not target.exists()


def test_office_identity_zip_paths_and_full_text_content_are_checked(tmp_path):
    renamed=tmp_path/'renamed.xlsx'
    with zipfile.ZipFile(renamed,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml','''<?xml version="1.0"?>
          <Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
            <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
          </Types>''')
        archive.writestr('word/document.xml','<document/>')
        archive.writestr('xl/workbook.xml','<workbook/>')
    with pytest.raises(UploadSecurityError,match='does not match'):
        validate_workbook_file(renamed,renamed.name,8*1024*1024)

    unsafe=tmp_path/'unsafe.xlsx'
    with zipfile.ZipFile(unsafe,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml','<Types/>')
        archive.writestr('../escape.txt','no')
    with pytest.raises(UploadSecurityError,match='unsafe internal path'):
        validate_workbook_file(unsafe,unsafe.name,8*1024*1024)

    binary_text=tmp_path/'binary.txt';binary_text.write_bytes(b'normal first bytes'+b'\x00'+b'x'*100)
    with pytest.raises(UploadSecurityError,match='does not match'):
        validate_attachment_file(binary_text,binary_text.name,{'.txt'},1024)


def test_import_preview_rejects_disguised_workbook_before_parsing():
    client=TestClient(app)
    login=client.post('/api/auth/login',json={'username':'admin','password':'ChangeMe123!'})
    headers={'Authorization':'Bearer '+login.json()['access_token']}
    response=client.post(
        '/api/import/preview/excel',
        headers=headers,
        files={'file':('malicious.xlsx',b'not-an-office-package','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')},
    )
    assert response.status_code == 422
    assert 'Office Open XML' in response.text


def test_import_preview_enforces_configured_compressed_size_limit(tmp_path):
    settings=import_preview_api.get_settings()
    previous=(settings.upload_dir,settings.import_max_mb)
    settings.upload_dir=str(tmp_path/'imports');settings.import_max_mb=1
    try:
        client=TestClient(app)
        login=client.post('/api/auth/login',json={'username':'admin','password':'ChangeMe123!'})
        headers={'Authorization':'Bearer '+login.json()['access_token']}
        response=client.post(
            '/api/import/preview/historical-daily-mis',
            headers=headers,
            files={'file':('oversize.xlsx',b'x'*(1024*1024+1))},
        )
        assert response.status_code==413
        assert '1 MB limit' in response.text
    finally:
        settings.upload_dir,settings.import_max_mb=previous

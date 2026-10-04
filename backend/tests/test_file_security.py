from pathlib import Path

import pytest
from openpyxl import Workbook

from app.services.file_security import (
    UploadSecurityError,
    safe_path,
    validate_attachment_file,
    validate_workbook_file,
)


def test_valid_workbook_and_safe_attachment_types(tmp_path):
    workbook=tmp_path/'valid.xlsx'
    wb=Workbook();wb.active['A1']='Plan';wb.save(workbook)
    validate_workbook_file(workbook,'valid.xlsx',128*1024*1024)
    mime=validate_attachment_file(workbook,'evidence.xlsx',{'.xlsx'},128*1024*1024)
    assert 'spreadsheetml' in mime

    pdf=tmp_path/'evidence.pdf';pdf.write_bytes(b'%PDF-1.7\nminimal-test')
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

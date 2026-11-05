from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from app.api import actions as actions_api
from app.db import SessionLocal
from app.main import app
from app.models import Action, ActionAttachment
from app.services.file_security import hash_file
from test_governance_security import headers


def _seed_attachment(tmp_path: Path, *, file_name: str, contents: bytes):
    action_no = "ACT-2026-DOC001"
    relative = Path(action_no) / file_name
    target = tmp_path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(contents)

    with SessionLocal() as db:
        action = Action(
            action_no=action_no,
            reference_date=date(2026, 11, 5),
            problem_category="Process",
            problem_description="Repeated spindle vibration during finish machining",
            action_description="Check fixture and spindle bearing condition",
        )
        db.add(action)
        db.flush()
        attachment = ActionAttachment(
            action_id=action.id,
            file_name=file_name,
            stored_name=file_name,
            relative_path=relative.as_posix(),
            mime_type="text/plain" if file_name.endswith(".txt") else "application/pdf",
            size_bytes=len(contents),
            sha256=hash_file(target),
            caption="Machine inspection evidence",
        )
        db.add(attachment)
        db.commit()
        return action.id, attachment.id, target


def test_knowledge_search_finds_text_content_and_returns_authorized_source_link(tmp_path):
    action_id, attachment_id, target = _seed_attachment(
        tmp_path,
        file_name="inspection.txt",
        contents=b"Inspection result: spindle bearing clearance exceeded the standard limit.",
    )
    old_dir = actions_api.settings.attachments_dir
    actions_api.settings.attachments_dir = str(tmp_path)
    try:
        client = TestClient(app)
        response = client.get(
            "/api/actions/knowledge-search?q=bearing%20clearance",
            headers=headers(client),
        )
    finally:
        actions_api.settings.attachments_dir = old_dir

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["query"] == "bearing clearance"
    assert len(body["results"]) == 1
    row = body["results"][0]
    assert row["action_id"] == action_id
    assert row["attachment_id"] == attachment_id
    assert row["match_source"] == "document text"
    assert "bearing clearance" in row["excerpt"].lower()
    assert row["download_path"] == f"/actions/{action_id}/attachments/{attachment_id}"
    assert target.is_file()


def test_knowledge_search_rejects_tampered_files_even_when_metadata_matches(tmp_path):
    action_id, attachment_id, target = _seed_attachment(
        tmp_path,
        file_name="inspection.txt",
        contents=b"Original evidence content",
    )
    target.write_text("Tampered evidence content", encoding="utf-8")
    old_dir = actions_api.settings.attachments_dir
    actions_api.settings.attachments_dir = str(tmp_path)
    try:
        client = TestClient(app)
        content_search = client.get(
            "/api/actions/knowledge-search?q=tampered",
            headers=headers(client),
        )
        metadata_search = client.get(
            "/api/actions/knowledge-search?q=inspection.txt",
            headers=headers(client),
        )
    finally:
        actions_api.settings.attachments_dir = old_dir

    assert content_search.status_code == 200, content_search.text
    assert content_search.json()["results"] == []
    # The complete attachment record is excluded if the integrity check fails,
    # even when the query would match its filename.
    assert metadata_search.status_code == 200, metadata_search.text
    assert metadata_search.json()["results"] == []

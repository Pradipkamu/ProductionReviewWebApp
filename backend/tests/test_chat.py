from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import hash_password
from app.db import SessionLocal
from app.enums import UserRole
from app.main import app
from app.models import User, ChatConversation, ChatParticipant, ChatMessage


client = TestClient(app)


def _headers():
    response = client.post("/api/auth/login", json={
        "username": "admin", "password": "ChangeMe123!",
    })
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _employee(username: str, *, chat_disabled: bool = False) -> int:
    with SessionLocal() as db:
        user = User(
            username=username,
            password_hash=hash_password("Employee123!"),
            full_name=username.title(),
            role=UserRole.VIEW_ONLY,
            is_active=True,
            must_change_password=False,
            chat_disabled=chat_disabled,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id


def test_direct_chat_message_and_unread_count():
    headers = _headers()
    employee_id = _employee("chat_direct_user")

    created = client.post("/api/chat/conversations/direct", headers=headers,
                          json={"user_id": employee_id})
    assert created.status_code == 200, created.text
    conversation_id = created.json()["id"]

    sent = client.post(f"/api/chat/conversations/{conversation_id}/messages",
                       headers=headers, json={"body": "Production update"})
    assert sent.status_code == 200, sent.text
    assert sent.json()["body"] == "Production update"

    with SessionLocal() as db:
        row = db.scalar(select(ChatMessage).where(ChatMessage.conversation_id == conversation_id))
        assert row is not None
        assert row.body == "Production update"

    employee_login = client.post("/api/auth/login", json={
        "username": "chat_direct_user", "password": "Employee123!",
    })
    assert employee_login.status_code == 200, employee_login.text
    employee_headers = {"Authorization": f"Bearer {employee_login.json()['access_token']}"}
    listing = client.get("/api/chat/conversations", headers=employee_headers)
    assert listing.status_code == 200, listing.text
    assert listing.json()[0]["unread_count"] == 1


def test_chat_disabled_employee_cannot_be_searched_or_added():
    headers = _headers()
    disabled_id = _employee("chat_disabled_user", chat_disabled=True)

    search = client.get("/api/chat/employees?q=chat_disabled_user", headers=headers)
    assert search.status_code == 200, search.text
    assert all(row["id"] != disabled_id for row in search.json())

    direct = client.post("/api/chat/conversations/direct", headers=headers,
                         json={"user_id": disabled_id})
    assert direct.status_code == 404

    group = client.post("/api/chat/conversations/group", headers=headers,
                        json={"title": "Test group", "user_ids": [disabled_id]})
    assert group.status_code == 400


def test_group_member_permissions_and_private_conversation_access():
    headers = _headers()
    first_id = _employee("chat_group_first")
    second_id = _employee("chat_group_second")

    created = client.post("/api/chat/conversations/group", headers=headers,
                          json={"title": "Shift A", "user_ids": [first_id]})
    assert created.status_code == 200, created.text
    conversation_id = created.json()["id"]

    first_login = client.post("/api/auth/login", json={
        "username": "chat_group_first", "password": "Employee123!",
    })
    assert first_login.status_code == 200, first_login.text
    first_headers = {"Authorization": f"Bearer {first_login.json()['access_token']}"}

    added = client.post(f"/api/chat/conversations/{conversation_id}/members",
                        headers=first_headers, json={"user_ids": [second_id]})
    assert added.status_code == 403

    second_login = client.post("/api/auth/login", json={
        "username": "chat_group_second", "password": "Employee123!",
    })
    assert second_login.status_code == 200, second_login.text
    second_headers = {"Authorization": f"Bearer {second_login.json()['access_token']}"}
    private_read = client.get(f"/api/chat/conversations/{conversation_id}/messages",
                              headers=second_headers)
    assert private_read.status_code == 404

    with SessionLocal() as db:
        participants = db.scalars(select(ChatParticipant).where(
            ChatParticipant.conversation_id == conversation_id,
            ChatParticipant.is_active.is_(True),
        )).all()
        admin_id = db.scalar(select(User.id).where(User.username == "admin"))
        assert {row.user_id for row in participants} == {admin_id, first_id}

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import uuid

import jwt
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..config import get_settings
from ..db import SessionLocal, get_db
from ..enums import UserRole
from ..models import ChatAttachment, ChatConversation, ChatMessage, ChatParticipant, ChatReport, User, UserSession
from ..page_access import can_send_chat
from ..services.file_security import UploadSecurityError, hash_file, safe_original_name, safe_path, save_limited_stream, validate_attachment_file

def require_chat_access(user: User = Depends(get_current_user)):
    return user

def require_chat_sender(db: Session, user: User):
    if not can_send_chat(db, user):
        raise HTTPException(403, "Your role is not permitted to send chat messages")


router = APIRouter(prefix="/chat", tags=["chat"], dependencies=[Depends(require_chat_access)])
settings = get_settings()
CHAT_MAX_BYTES = 12 * 1024 * 1024
CHAT_ALLOWED = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".docx", ".xlsx", ".pptx", ".txt", ".csv"}


class DirectConversationCreate(BaseModel):
    user_id: int = Field(gt=0)


class GroupConversationCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    user_ids: list[int] = Field(min_length=1, max_length=100)


class MessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=10000)


class GroupMemberAdd(BaseModel):
    user_ids: list[int] = Field(min_length=1, max_length=100)


class ReportCreate(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class ReportResolve(BaseModel):
    status: str = Field(pattern="^(RESOLVED|DISMISSED)$")


class ChatSocketHub:
    def __init__(self):
        self.connections: dict[int, set[WebSocket]] = {}

    async def connect(self, user_id: int, socket: WebSocket):
        await socket.accept()
        self.connections.setdefault(user_id, set()).add(socket)

    def disconnect(self, user_id: int, socket: WebSocket):
        self.connections.get(user_id, set()).discard(socket)
        if not self.connections.get(user_id):
            self.connections.pop(user_id, None)

    async def notify(self, user_ids: list[int], event: dict):
        for uid in set(user_ids):
            for socket in list(self.connections.get(uid, set())):
                try:
                    await socket.send_json(event)
                except Exception:
                    self.disconnect(uid, socket)


hub = ChatSocketHub()


def _participant(db: Session, conversation_id: int, user_id: int):
    row = db.scalar(select(ChatParticipant).where(
        ChatParticipant.conversation_id == conversation_id,
        ChatParticipant.user_id == user_id,
        ChatParticipant.is_active.is_(True),
    ))
    if not row:
        raise HTTPException(404, "Conversation not found")
    return row


def _active_participant_ids(db: Session, conversation_id: int) -> list[int]:
    return list(db.scalars(select(ChatParticipant.user_id).where(
        ChatParticipant.conversation_id == conversation_id, ChatParticipant.is_active.is_(True)
    )).all())


def _serialize_message(db: Session, msg: ChatMessage, full_name: str | None = None, username: str | None = None):
    sender = db.get(User, msg.sender_id)
    attachments = db.scalars(select(ChatAttachment).where(ChatAttachment.message_id == msg.id)).all()
    return {
        "id": msg.id, "conversation_id": msg.conversation_id, "sender_id": msg.sender_id,
        "sender_name": full_name or (sender.full_name if sender else "Former user"),
        "sender_username": username or (sender.username if sender else ""),
        "body": msg.body, "message_type": msg.message_type, "created_at": msg.created_at,
        "attachments": [{"id": a.id, "file_name": a.file_name, "mime_type": a.mime_type,
                         "size_bytes": a.size_bytes, "download_url": f"/chat/attachments/{a.id}"}
                        for a in attachments],
    }


def _conversation_summary(db: Session, conversation: ChatConversation, user_id: int):
    participants = db.execute(
        select(User.id, User.full_name, User.username)
        .join(ChatParticipant, ChatParticipant.user_id == User.id)
        .where(ChatParticipant.conversation_id == conversation.id,
               ChatParticipant.is_active.is_(True), User.is_active.is_(True))
        .order_by(User.full_name)
    ).all()
    mine = db.scalar(select(ChatParticipant).where(
        ChatParticipant.conversation_id == conversation.id, ChatParticipant.user_id == user_id))
    last_message = db.scalar(select(ChatMessage).where(
        ChatMessage.conversation_id == conversation.id, ChatMessage.deleted_at.is_(None)
    ).order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc()).limit(1))
    unread = db.scalar(select(func.count(ChatMessage.id)).where(
        ChatMessage.conversation_id == conversation.id, ChatMessage.sender_id != user_id,
        ChatMessage.deleted_at.is_(None),
        ChatMessage.created_at > (mine.last_read_at if mine and mine.last_read_at else datetime.min),
    )) or 0
    return {
        "id": conversation.id, "kind": conversation.kind, "title": conversation.title,
        "created_by_id": conversation.created_by_id,
        "participants": [{"id": x.id, "full_name": x.full_name, "username": x.username} for x in participants],
        "last_message": _serialize_message(db, last_message) if last_message else None,
        "unread_count": unread, "updated_at": conversation.updated_at,
    }


def _admin(user: User):
    if user.role != UserRole.ADMIN:
        raise HTTPException(403, "Administrator access required")


@router.get("/employees")
def employees(q: str = Query(default="", max_length=100), db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    term = q.strip()
    stmt = select(User).where(User.is_active.is_(True), User.id != user.id)
    if term:
        pattern = f"%{term}%"
        stmt = stmt.where(or_(User.full_name.ilike(pattern), User.username.ilike(pattern)))
    rows = db.scalars(stmt.order_by(User.full_name, User.username).limit(100)).all()
    return [{"id": row.id, "full_name": row.full_name, "username": row.username, "role": row.role.value, "chat_enabled": not row.chat_disabled}
            for row in rows]


@router.get("/conversations")
def conversations(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(select(ChatConversation).join(ChatParticipant).where(
        ChatParticipant.user_id == user.id, ChatParticipant.is_active.is_(True),
        ChatConversation.is_active.is_(True)
    ).order_by(ChatConversation.updated_at.desc(), ChatConversation.id.desc())).unique().all()
    return [_conversation_summary(db, row, user.id) for row in rows]


@router.post("/conversations/direct")
def create_direct(payload: DirectConversationCreate, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    require_chat_sender(db, user)
    if payload.user_id == user.id:
        raise HTTPException(400, "You cannot start a direct conversation with yourself")
    target = db.scalar(select(User).where(User.id == payload.user_id, User.is_active.is_(True)))
    if not target:
        raise HTTPException(404, "Employee not found")
    existing = db.scalar(select(ChatConversation).join(ChatParticipant).where(
        ChatConversation.kind == "DIRECT", ChatConversation.is_active.is_(True),
        ChatParticipant.user_id == user.id, ChatParticipant.is_active.is_(True),
        ChatConversation.id.in_(select(ChatParticipant.conversation_id).where(
            ChatParticipant.user_id == target.id, ChatParticipant.is_active.is_(True)))
    ).limit(1))
    if existing and set(_active_participant_ids(db, existing.id)) == {user.id, target.id}:
        return _conversation_summary(db, existing, user.id)
    row = ChatConversation(kind="DIRECT", created_by_id=user.id)
    db.add(row); db.flush()
    db.add_all([ChatParticipant(conversation_id=row.id, user_id=user.id, last_read_at=datetime.utcnow()),
                ChatParticipant(conversation_id=row.id, user_id=target.id)])
    db.commit(); db.refresh(row)
    return _conversation_summary(db, row, user.id)


@router.post("/conversations/group")
def create_group(payload: GroupConversationCreate, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    require_chat_sender(db, user)
    user_ids = list(dict.fromkeys([user.id, *payload.user_ids]))
    active_ids = set(db.scalars(select(User.id).where(User.id.in_(user_ids), User.is_active.is_(True))).all())
    if active_ids != set(user_ids):
        raise HTTPException(400, "One or more selected employees are unavailable or have chat disabled")
    row = ChatConversation(kind="GROUP", title=payload.title.strip(), created_by_id=user.id)
    db.add(row); db.flush()
    db.add_all([ChatParticipant(conversation_id=row.id, user_id=uid,
                                last_read_at=datetime.utcnow() if uid == user.id else None) for uid in user_ids])
    db.commit(); db.refresh(row)
    return _conversation_summary(db, row, user.id)


@router.post("/conversations/{conversation_id}/members")
async def add_group_members(conversation_id: int, payload: GroupMemberAdd,
                            db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    conversation = db.get(ChatConversation, conversation_id)
    if not conversation or conversation.kind != "GROUP":
        raise HTTPException(404, "Group conversation not found")
    require_chat_sender(db, user)
    if user.role != UserRole.ADMIN:
        _participant(db, conversation_id, user.id)
    if conversation.created_by_id != user.id and user.role != UserRole.ADMIN:
        raise HTTPException(403, "Only the group creator or an administrator can add members")
    ids = list(dict.fromkeys(payload.user_ids))
    users = db.scalars(select(User).where(User.id.in_(ids), User.is_active.is_(True))).all()
    if len(users) != len(ids):
        raise HTTPException(400, "One or more selected employees are unavailable")
    for uid in ids:
        row = db.scalar(select(ChatParticipant).where(ChatParticipant.conversation_id == conversation_id,
                                                       ChatParticipant.user_id == uid))
        if row:
            row.is_active = True
        else:
            db.add(ChatParticipant(conversation_id=conversation_id, user_id=uid))
    conversation.updated_at = datetime.utcnow()
    db.commit()
    await hub.notify(ids, {"type": "conversation_updated", "conversation_id": conversation_id})
    return _conversation_summary(db, conversation, user.id)


@router.post("/conversations/{conversation_id}/leave")
def leave_group(conversation_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    conversation = db.get(ChatConversation, conversation_id)
    if not conversation or conversation.kind != "GROUP":
        raise HTTPException(404, "Group conversation not found")
    participant = _participant(db, conversation_id, user.id)
    participant.is_active = False
    conversation.updated_at = datetime.utcnow()
    db.commit()
    return {"success": True}


@router.get("/conversations/{conversation_id}/messages")
def messages(conversation_id: int, before_id: Optional[int] = None,
             limit: int = Query(default=50, ge=1, le=100), db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    participant = _participant(db, conversation_id, user.id)
    stmt = select(ChatMessage, User.full_name, User.username).join(User, User.id == ChatMessage.sender_id).where(
        ChatMessage.conversation_id == conversation_id, ChatMessage.deleted_at.is_(None))
    if before_id:
        stmt = stmt.where(ChatMessage.id < before_id)
    rows = db.execute(stmt.order_by(ChatMessage.id.desc()).limit(limit)).all()
    participant.last_read_at = datetime.utcnow()
    db.commit()
    return [_serialize_message(db, msg, full_name, username) for msg, full_name, username in reversed(rows)]


@router.post("/conversations/{conversation_id}/messages")
async def send_message(conversation_id: int, payload: MessageCreate, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    _participant(db, conversation_id, user.id)
    require_chat_sender(db, user)
    body = payload.body.strip()
    if not body:
        raise HTTPException(422, "Message cannot be empty")
    conversation = db.get(ChatConversation, conversation_id)
    if not conversation or not conversation.is_active:
        raise HTTPException(404, "Conversation not found")
    now = datetime.utcnow()
    row = ChatMessage(conversation_id=conversation_id, sender_id=user.id, body=body)
    db.add(row); conversation.updated_at = now
    own = db.scalar(select(ChatParticipant).where(ChatParticipant.conversation_id == conversation_id,
                                                    ChatParticipant.user_id == user.id))
    if own: own.last_read_at = now
    db.commit(); db.refresh(row)
    result = _serialize_message(db, row, user.full_name, user.username)
    await hub.notify(_active_participant_ids(db, conversation_id),
                     {"type": "new_message", "conversation_id": conversation_id, "message": result})
    return result


@router.post("/conversations/{conversation_id}/messages/{message_id}/attachments")
async def upload_attachment(conversation_id: int, message_id: int, file: UploadFile = File(...),
                            db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _participant(db, conversation_id, user.id)
    require_chat_sender(db, user)
    msg = db.scalar(select(ChatMessage).where(ChatMessage.id == message_id,
                                               ChatMessage.conversation_id == conversation_id))
    if not msg or msg.sender_id != user.id:
        raise HTTPException(404, "Message not found")
    original = safe_original_name(file.filename, "chat-attachment")
    root = Path(settings.attachments_dir).resolve() / "chat"
    stored = f"{uuid.uuid4().hex}{Path(original).suffix.lower()}"
    target = safe_path(root, stored)
    try:
        size, digest = save_limited_stream(file.file, target, CHAT_MAX_BYTES)
        mime = validate_attachment_file(target, original, CHAT_ALLOWED,
                                        settings.office_max_uncompressed_mb * 1024 * 1024)
    except UploadSecurityError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    except Exception:
        target.unlink(missing_ok=True)
        raise
    row = ChatAttachment(message_id=msg.id, file_name=original, stored_name=stored,
                         relative_path=stored, mime_type=mime, size_bytes=size,
                         sha256=digest, uploaded_by_id=user.id)
    db.add(row); db.commit(); db.refresh(row)
    result = {"id": row.id, "file_name": row.file_name, "mime_type": row.mime_type,
              "size_bytes": row.size_bytes, "download_url": f"/chat/attachments/{row.id}"}
    await hub.notify(_active_participant_ids(db, conversation_id),
                     {"type": "attachment_added", "conversation_id": conversation_id, "attachment": result})
    return result


@router.get("/attachments/{attachment_id}")
def download_attachment(attachment_id: int, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    row = db.get(ChatAttachment, attachment_id)
    if not row:
        raise HTTPException(404, "Attachment not found")
    msg = db.get(ChatMessage, row.message_id)
    if not msg:
        raise HTTPException(404, "Attachment not found")
    _participant(db, msg.conversation_id, user.id)
    path = safe_path(Path(settings.attachments_dir).resolve() / "chat", row.relative_path)
    if not path.is_file() or hash_file(path) != row.sha256:
        raise HTTPException(404, "Attachment file is unavailable or failed integrity validation")
    return FileResponse(path, filename=row.file_name, media_type=row.mime_type)


@router.post("/messages/{message_id}/report")
def report_message(message_id: int, payload: ReportCreate, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    msg = db.get(ChatMessage, message_id)
    if not msg:
        raise HTTPException(404, "Message not found")
    _participant(db, msg.conversation_id, user.id)
    row = ChatReport(message_id=message_id, reported_by_id=user.id, reason=payload.reason.strip())
    db.add(row)
    try: db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(409, "You have already reported this message")
    return {"success": True}


@router.get("/admin/users")
def admin_chat_users(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _admin(user)
    rows = db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.full_name, User.username)).all()
    return [{"id": row.id, "full_name": row.full_name, "username": row.username,
             "role": row.role.value, "chat_enabled": not row.chat_disabled} for row in rows]


@router.get("/admin/reports")
def admin_reports(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _admin(user)
    rows = db.scalars(select(ChatReport).order_by(ChatReport.created_at.desc()).limit(300)).all()
    result = []
    for report in rows:
        msg = db.get(ChatMessage, report.message_id)
        reporter = db.get(User, report.reported_by_id)
        sender = db.get(User, msg.sender_id) if msg else None
        result.append({"id": report.id, "message_id": report.message_id, "reason": report.reason,
                       "status": report.status, "created_at": report.created_at,
                       "reporter": reporter.full_name if reporter else "Former user",
                       "sender": sender.full_name if sender else "Former user",
                       "message": msg.body if msg else "[message unavailable]"})
    return result


@router.patch("/admin/reports/{report_id}")
def resolve_report(report_id: int, payload: ReportResolve, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    _admin(user)
    report = db.get(ChatReport, report_id)
    if not report:
        raise HTTPException(404, "Report not found")
    report.status = payload.status
    report.resolved_by_id = user.id
    report.resolved_at = datetime.utcnow()
    db.commit()
    return {"success": True, "status": report.status}


@router.delete("/admin/messages/{message_id}")
async def moderate_message(message_id: int, db: Session = Depends(get_db),
                           user: User = Depends(get_current_user)):
    _admin(user)
    msg = db.get(ChatMessage, message_id)
    if not msg:
        raise HTTPException(404, "Message not found")
    msg.deleted_at = datetime.utcnow()
    db.commit()
    await hub.notify(_active_participant_ids(db, msg.conversation_id),
                     {"type": "message_removed", "conversation_id": msg.conversation_id, "message_id": message_id})
    return {"success": True}


@router.patch("/admin/users/{user_id}/chat-access")
def set_chat_access(user_id: int, enabled: bool = Query(...), db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    _admin(user)
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "Employee not found")
    if target.id == user.id and not enabled:
        raise HTTPException(400, "You cannot disable your own chat access")
    target.chat_disabled = not enabled
    db.commit()
    return {"success": True, "chat_enabled": enabled}


@router.websocket("/ws")
async def chat_socket(socket: WebSocket, token: str = Query(...)):
    db = SessionLocal()
    user_id = None
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        user_id = int(payload.get("sub"))
        session_id = str(payload.get("sid") or "")
        user = db.scalar(select(User).where(User.id == user_id, User.is_active.is_(True)))
        session = db.scalar(select(UserSession).where(UserSession.session_id == session_id,
                                                       UserSession.user_id == user_id))
        now = datetime.utcnow()
        if (not user or not session or session.revoked_at is not None or
                session.expires_at <= now or
                session.last_seen_at + timedelta(minutes=settings.session_idle_timeout_minutes) <= now or
                payload.get("ver") != user.token_version):
            await socket.close(code=4401); return
        # Receive-only users remain connected for incoming messages.
        await hub.connect(user_id, socket)
        while True:
            try:
                await asyncio.wait_for(socket.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                # WebSocket connections must not outlive the same session policy as REST.
                db.expire_all()
                user = db.scalar(select(User).where(User.id == user_id, User.is_active.is_(True)))
                session = db.scalar(select(UserSession).where(
                    UserSession.session_id == session_id, UserSession.user_id == user_id))
                now = datetime.utcnow()
                if not user or not session or session.revoked_at is not None or session.expires_at <= now:
                    await socket.close(code=4401); return
                if session.last_seen_at + timedelta(minutes=settings.session_idle_timeout_minutes) <= now:
                    await socket.close(code=4401); return
                # Receive-only users remain connected for incoming messages.
    except WebSocketDisconnect:
        pass
    except Exception:
        try: await socket.close(code=4401)
        except Exception: pass
    finally:
        if user_id is not None: hub.disconnect(user_id, socket)
        db.close()

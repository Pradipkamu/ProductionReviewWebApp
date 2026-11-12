from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import ChatConversation, ChatMessage, ChatParticipant, User

router = APIRouter(prefix="/chat", tags=["chat"])


class DirectConversationCreate(BaseModel):
    user_id: int = Field(gt=0)


class GroupConversationCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    user_ids: list[int] = Field(min_length=1, max_length=100)


class MessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=10000)


def _participant(db: Session, conversation_id: int, user_id: int):
    row = db.scalar(select(ChatParticipant).where(
        ChatParticipant.conversation_id == conversation_id,
        ChatParticipant.user_id == user_id,
        ChatParticipant.is_active.is_(True),
    ))
    if not row:
        raise HTTPException(404, "Conversation not found")
    return row


def _conversation_summary(db: Session, conversation: ChatConversation, user_id: int):
    participants = db.execute(
        select(User.id, User.full_name, User.username)
        .join(ChatParticipant, ChatParticipant.user_id == User.id)
        .where(ChatParticipant.conversation_id == conversation.id,
               ChatParticipant.is_active.is_(True), User.is_active.is_(True))
        .order_by(User.full_name)
    ).all()
    mine = db.scalar(select(ChatParticipant).where(
        ChatParticipant.conversation_id == conversation.id,
        ChatParticipant.user_id == user_id,
    ))
    last_message = db.scalar(select(ChatMessage).where(
        ChatMessage.conversation_id == conversation.id,
        ChatMessage.deleted_at.is_(None),
    ).order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc()).limit(1))
    unread = db.scalar(select(func.count(ChatMessage.id)).where(
        ChatMessage.conversation_id == conversation.id,
        ChatMessage.sender_id != user_id,
        ChatMessage.deleted_at.is_(None),
        ChatMessage.created_at > (mine.last_read_at if mine and mine.last_read_at else datetime.min),
    )) or 0
    return {
        "id": conversation.id,
        "kind": conversation.kind,
        "title": conversation.title,
        "participants": [{"id": x.id, "full_name": x.full_name, "username": x.username} for x in participants],
        "last_message": ({"id": last_message.id, "body": last_message.body,
                          "sender_id": last_message.sender_id, "created_at": last_message.created_at}
                         if last_message else None),
        "unread_count": unread,
        "updated_at": conversation.updated_at,
    }


@router.get("/employees")
def employees(q: str = Query(default="", max_length=100), db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    term = q.strip()
    stmt = select(User).where(User.is_active.is_(True), User.id != user.id)
    if term:
        pattern = f"%{term}%"
        stmt = stmt.where(or_(User.full_name.ilike(pattern), User.username.ilike(pattern)))
    rows = db.scalars(stmt.order_by(User.full_name, User.username).limit(100)).all()
    return [{"id": row.id, "full_name": row.full_name, "username": row.username, "role": row.role.value}
            for row in rows]


@router.get("/conversations")
def conversations(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(
        select(ChatConversation).join(ChatParticipant)
        .where(ChatParticipant.user_id == user.id, ChatParticipant.is_active.is_(True),
               ChatConversation.is_active.is_(True))
        .order_by(ChatConversation.updated_at.desc(), ChatConversation.id.desc())
    ).unique().all()
    return [_conversation_summary(db, row, user.id) for row in rows]


@router.post("/conversations/direct")
def create_direct(payload: DirectConversationCreate, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    if payload.user_id == user.id:
        raise HTTPException(400, "You cannot start a direct conversation with yourself")
    target = db.scalar(select(User).where(User.id == payload.user_id, User.is_active.is_(True)))
    if not target:
        raise HTTPException(404, "Employee not found")
    existing = db.scalar(
        select(ChatConversation).join(ChatParticipant)
        .where(ChatConversation.kind == "DIRECT", ChatConversation.is_active.is_(True),
               ChatParticipant.user_id == user.id, ChatParticipant.is_active.is_(True),
               ChatConversation.id.in_(
                   select(ChatParticipant.conversation_id).where(
                       ChatParticipant.user_id == target.id, ChatParticipant.is_active.is_(True))
               ))
        .limit(1)
    )
    if existing:
        return _conversation_summary(db, existing, user.id)
    row = ChatConversation(kind="DIRECT", created_by_id=user.id)
    db.add(row)
    db.flush()
    db.add_all([
        ChatParticipant(conversation_id=row.id, user_id=user.id, last_read_at=datetime.utcnow()),
        ChatParticipant(conversation_id=row.id, user_id=target.id),
    ])
    db.commit()
    db.refresh(row)
    return _conversation_summary(db, row, user.id)


@router.post("/conversations/group")
def create_group(payload: GroupConversationCreate, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    user_ids = list(dict.fromkeys([user.id, *payload.user_ids]))
    active_ids = set(db.scalars(select(User.id).where(User.id.in_(user_ids), User.is_active.is_(True))).all())
    if active_ids != set(user_ids):
        raise HTTPException(400, "One or more selected employees are unavailable")
    row = ChatConversation(kind="GROUP", title=payload.title.strip(), created_by_id=user.id)
    db.add(row)
    db.flush()
    db.add_all([ChatParticipant(conversation_id=row.id, user_id=uid,
                                last_read_at=datetime.utcnow() if uid == user.id else None)
                for uid in user_ids])
    db.commit()
    db.refresh(row)
    return _conversation_summary(db, row, user.id)


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
    return [{"id": msg.id, "conversation_id": msg.conversation_id, "sender_id": msg.sender_id,
             "sender_name": full_name, "sender_username": username, "body": msg.body,
             "message_type": msg.message_type, "created_at": msg.created_at}
            for msg, full_name, username in reversed(rows)]


@router.post("/conversations/{conversation_id}/messages")
def send_message(conversation_id: int, payload: MessageCreate, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    _participant(db, conversation_id, user.id)
    body = payload.body.strip()
    if not body:
        raise HTTPException(422, "Message cannot be empty")
    conversation = db.get(ChatConversation, conversation_id)
    if not conversation or not conversation.is_active:
        raise HTTPException(404, "Conversation not found")
    row = ChatMessage(conversation_id=conversation_id, sender_id=user.id, body=body)
    db.add(row)
    conversation.updated_at = datetime.utcnow()
    own = db.scalar(select(ChatParticipant).where(
        ChatParticipant.conversation_id == conversation_id, ChatParticipant.user_id == user.id))
    if own:
        own.last_read_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return {"id": row.id, "conversation_id": row.conversation_id, "sender_id": row.sender_id,
            "sender_name": user.full_name, "sender_username": user.username, "body": row.body,
            "message_type": row.message_type, "created_at": row.created_at}


@router.post("/conversations/{conversation_id}/read")
def mark_read(conversation_id: int, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    participant = _participant(db, conversation_id, user.id)
    participant.last_read_at = datetime.utcnow()
    db.commit()
    return {"success": True}

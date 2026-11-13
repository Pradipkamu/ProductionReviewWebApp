"""Direct Chat delivery for automated action notifications.

Notifications are persisted as ordinary direct-chat messages from a reserved
system user. The system account is created with an unguessable password and
is never used for interactive sign-in.
"""
from __future__ import annotations

import secrets
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import hash_password
from ..enums import UserRole
from ..models import (
    Action, AlertDeliveryLog, ChatConversation, ChatMessage, ChatParticipant, User,
)


SYSTEM_USERNAME = "production-review-system"
SYSTEM_DISPLAY_NAME = "Production Review System"


def _system_user(db: Session) -> User:
    user = db.scalar(select(User).where(User.username == SYSTEM_USERNAME))
    if user:
        if not user.is_active:
            user.is_active = True
        if user.full_name != SYSTEM_DISPLAY_NAME:
            user.full_name = SYSTEM_DISPLAY_NAME
        return user

    user = User(
        username=SYSTEM_USERNAME,
        password_hash=hash_password(secrets.token_urlsafe(64)),
        full_name=SYSTEM_DISPLAY_NAME,
        role=UserRole.VIEW_ONLY,
        is_active=True,
        must_change_password=False,
        chat_disabled=False,
    )
    db.add(user)
    db.flush()
    return user


def _direct_conversation(db: Session, system_user_id: int, recipient_id: int) -> ChatConversation:
    candidates = db.scalars(
        select(ChatConversation)
        .join(ChatParticipant, ChatParticipant.conversation_id == ChatConversation.id)
        .where(
            ChatConversation.kind == "DIRECT",
            ChatConversation.is_active.is_(True),
            ChatParticipant.user_id == system_user_id,
            ChatParticipant.is_active.is_(True),
            ChatConversation.id.in_(
                select(ChatParticipant.conversation_id).where(
                    ChatParticipant.user_id == recipient_id,
                    ChatParticipant.is_active.is_(True),
                )
            ),
        )
        .order_by(ChatConversation.id)
    ).all()
    for conversation in candidates:
        active_ids = set(db.scalars(select(ChatParticipant.user_id).where(
            ChatParticipant.conversation_id == conversation.id,
            ChatParticipant.is_active.is_(True),
        )).all())
        if active_ids == {system_user_id, recipient_id}:
            return conversation

    conversation = ChatConversation(kind="DIRECT", created_by_id=system_user_id)
    db.add(conversation)
    db.flush()
    db.add_all([
        ChatParticipant(
            conversation_id=conversation.id,
            user_id=system_user_id,
            last_read_at=datetime.utcnow(),
        ),
        ChatParticipant(conversation_id=conversation.id, user_id=recipient_id),
    ])
    db.flush()
    return conversation


def send_action_chat_notification(
    db: Session,
    action: Action,
    recipient_id: int,
    *,
    kind: str,
    event_key: str,
    message: str,
    policy_id: int | None = None,
) -> bool:
    """Create one idempotent system-to-user chat message for an action event."""
    recipient = db.scalar(select(User).where(
        User.id == recipient_id,
        User.is_active.is_(True),
        User.chat_disabled.is_(False),
    ))
    if not recipient:
        return False

    existing = db.scalar(select(AlertDeliveryLog.id).where(
        AlertDeliveryLog.policy_id == policy_id,
        AlertDeliveryLog.event_key == event_key,
        AlertDeliveryLog.channel == "CHAT",
    ))
    if existing:
        return False

    system_user = _system_user(db)
    conversation = _direct_conversation(db, system_user.id, recipient.id)
    action_url = f"/actions?action_id={action.id}"
    body = (
        f"{message.strip()}\n\n"
        f"Action: {action.action_no}\n"
        f"Priority: {action.priority.value}\n"
        f"Open Action: {action_url}"
    )
    chat_message = ChatMessage(
        conversation_id=conversation.id,
        sender_id=system_user.id,
        body=body,
        message_type="TEXT",
    )
    db.add(chat_message)
    conversation.updated_at = datetime.utcnow()
    db.flush()

    db.add(AlertDeliveryLog(
        policy_id=policy_id,
        event_key=event_key,
        channel="CHAT",
        status="DELIVERED",
        recipient_role=recipient.role.value,
        message=body,
        delivered_at=datetime.utcnow(),
    ))
    return True

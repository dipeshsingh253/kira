from __future__ import annotations

from typing import Any

from sqlalchemy import ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.constants import (
    CHANNEL_API,
    CONVERSATION_STATUS_ACTIVE,
    MESSAGE_ROLE_AGENT,
)
from src.db.base import BaseModel


class Conversation(BaseModel):
    __tablename__ = "conversations"

    parent_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    parent_phone: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    channel: Mapped[str] = mapped_column(
        String(32),
        default=CHANNEL_API,
        nullable=False,
        comment="Conversation source such as api, voice_call, or whatsapp",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default=CONVERSATION_STATUS_ACTIVE,
        nullable=False,
        comment="Conversation lifecycle status such as active, paused, completed, or failed",
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    messages: Mapped[list["ConversationMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ConversationMessage.message_index",
    )


class ConversationMessage(BaseModel):
    __tablename__ = "conversation_messages"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "message_index",
            name="uq_conversation_messages_conversation_id_message_index",
        ),
    )

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        comment="ID of the conversation this message belongs to",
    )
    role: Mapped[str] = mapped_column(
        String(20),
        default=MESSAGE_ROLE_AGENT,
        nullable=False,
        comment="Message role such as user, agent, or system",
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    message_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="1-based message order within a conversation",
    )
    resolved_student_id: Mapped[str | None] = mapped_column(
        String(64),
        index=True,
        nullable=True,
    )
    message_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata",
        JSON,
        nullable=True,
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")

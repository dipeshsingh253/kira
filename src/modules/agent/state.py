from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypedDict

from langchain_core.messages import BaseMessage

from src.modules.conversations.model import Conversation, ConversationMessage
from src.modules.profiles.schemas import ParentProfile, StudentProfile


@dataclass(frozen=True)
class PersistedConversationMessage:
    role: str
    content: str
    created_at: datetime
    resolved_student_id: str | None = None
    metadata: dict[str, Any] | None = None

    @classmethod
    def from_message(cls, message: ConversationMessage) -> "PersistedConversationMessage":
        """Build the small runtime message shape from a saved conversation row."""
        return cls(
            role=message.role,
            content=message.content,
            created_at=message.created_at,
            resolved_student_id=message.resolved_student_id,
            metadata=message.message_metadata,
        )


class AgentGraphState(TypedDict, total=False):
    conversation: Conversation
    current_message: str
    context_messages: list[PersistedConversationMessage]
    parent_profile: ParentProfile
    resolved_student_id: str | None
    resolved_student: StudentProfile | None
    student_resolution_method: str
    student_resolution_explanation: str
    response_text: str
    provider: str | None
    model_name: str | None
    usage: dict[str, Any] | None
    model_input_messages: list[BaseMessage]
    summary_text: str | None
    summary_updated: bool
    summary_parent_turn_checkpoint: int | None

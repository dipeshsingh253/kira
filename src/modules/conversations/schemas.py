from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from src.core.constants import CHANNEL_API, CONVERSATION_CHANNELS
from src.modules.profiles.schemas import StudentProfile
from src.modules.profiles.utils import normalize_phone, normalize_phone_for_lookup


class ChildSummary(BaseModel):
    student_id: str
    name: str
    relation: str
    grade: str
    school: str

    @classmethod
    def from_profile(cls, child: StudentProfile) -> "ChildSummary":
        return cls(
            student_id=child.student_id,
            name=child.name,
            relation=child.relation,
            grade=child.grade,
            school=child.school,
        )


class ConversationStartRequest(BaseModel):
    parent_phone: str = Field(..., description="Parent phone number used to identify the parent profile")
    channel: str = Field(default=CHANNEL_API, description="Conversation channel")

    @field_validator("parent_phone")
    @classmethod
    def validate_parent_phone(cls, value: str) -> str:
        normalized = normalize_phone(value)
        if len(normalized) < 10:
            raise ValueError("parent_phone must contain at least 10 digits")
        return normalize_phone_for_lookup(normalized)

    @field_validator("channel")
    @classmethod
    def validate_channel(cls, value: str) -> str:
        if value not in CONVERSATION_CHANNELS:
            raise ValueError(f"channel must be one of: {', '.join(CONVERSATION_CHANNELS)}")
        return value


class ConversationStartResponse(BaseModel):
    conversation_id: str
    parent_id: str
    parent_name: str
    parent_phone: str
    children: list[ChildSummary]
    greeting: str


class ConversationMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, description="Parent message")
    debug: bool = Field(default=False, description="Include non-sensitive debug context")

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("message cannot be empty")
        return cleaned


class HistoryTurnDebug(BaseModel):
    role: str
    content: str
    resolved_student_id: str | None = None


class ConversationDebug(BaseModel):
    student_resolution_method: str
    student_resolution_explanation: str
    profile_facts_used: dict[str, Any]
    history_turns_used: list[HistoryTurnDebug]
    model_provider: str | None = None
    model_name: str | None = None
    summary_updated: bool = False


class ConversationMessageResponse(BaseModel):
    conversation_id: str
    message_id: str
    agent_message: str
    created_at: datetime
    resolved_student: ChildSummary | None = None
    debug: ConversationDebug | None = None


class ConversationMessageRecord(BaseModel):
    id: str
    role: str
    content: str
    created_at: datetime
    resolved_student: ChildSummary | None = None
    metadata: dict[str, Any] | None = None


class ConversationDetailResponse(BaseModel):
    conversation_id: str
    parent_id: str
    parent_name: str
    parent_phone: str
    channel: str
    status: str
    summary: str | None = None
    resolved_student: ChildSummary | None = None
    children: list[ChildSummary]
    messages: list[ConversationMessageRecord]

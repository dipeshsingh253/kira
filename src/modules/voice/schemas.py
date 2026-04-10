from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from src.core.constants import CHANNEL_VOICE_CALL


class VoiceInboundDecision(BaseModel):
    """Result of the inbound caller check that says whether this voice call is allowed in."""
    accepted: bool
    conversation_id: str | None = None
    parent_id: str | None = None
    parent_phone: str | None = None
    channel: str = CHANNEL_VOICE_CALL

    @classmethod
    def accepted_call(
        cls,
        *,
        conversation_id: str,
        parent_id: str,
        parent_phone: str,
    ) -> "VoiceInboundDecision":
        return cls(
            accepted=True,
            conversation_id=conversation_id,
            parent_id=parent_id,
            parent_phone=parent_phone,
        )

    @classmethod
    def rejected_call(cls) -> "VoiceInboundDecision":
        return cls(accepted=False)


class VoiceSessionRecord(BaseModel):
    """Live per-call state we keep in Redis while a voice conversation is in progress."""
    conversation_id: str
    parent_id: str
    parent_phone: str
    provider: str
    inbound_fingerprint: str
    provider_call_id: str | None = None
    greeting_persisted: bool = False
    latest_response_id: int | None = None
    last_processed_response_id: int | None = None
    last_processed_user_fingerprint: str | None = None
    last_agent_message_id: str | None = None
    last_agent_response_text: str | None = None
    follow_up_prompt_count: int = 0
    status: Literal["accepted", "active", "completed", "failed"] = "accepted"
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


class VoiceTurnResult(BaseModel):
    """Outcome of one handled voice turn, mainly the saved agent reply we just generated."""
    conversation_id: str
    agent_message_id: str
    agent_response_text: str
    cached: bool = False


class VoiceHealthStatus(BaseModel):
    """Health check shape for the voice layer and its backing session-store backend."""
    status: str
    backend: str
    details: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

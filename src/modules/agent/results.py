from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AgentDebugMessage(BaseModel):
    role: str
    content: str
    resolved_student_id: str | None = None


class AgentRunResult(BaseModel):
    """Small result object returned by the runtime for one turn.

    This keeps only the data the service still needs after the graph finishes. The
    service already has the parent profile and context window, so it can map student
    ids back to response objects on its own.
    """

    response_text: str
    resolved_student_id: str | None = None
    student_resolution_method: str
    student_resolution_explanation: str
    usage: dict[str, Any] | None = None
    model_name: str | None = None
    provider: str | None = None
    summary_text: str | None = None
    summary_updated: bool = False
    summary_parent_turn_checkpoint: int | None = None
    history_turns_used: list[AgentDebugMessage] = Field(default_factory=list)

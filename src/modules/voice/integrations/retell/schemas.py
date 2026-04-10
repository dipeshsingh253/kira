from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter


class RetellInboundCall(BaseModel):
    agent_id: str | None = None
    agent_version: int | None = None
    from_number: str
    to_number: str


class RetellInboundCallPayload(BaseModel):
    event: str
    call_inbound: RetellInboundCall


class RetellInboundCallResponseData(BaseModel):
    override_agent_id: str | None = None
    override_agent_version: int | None = None
    metadata: dict[str, Any] | None = None


class RetellInboundCallResponse(BaseModel):
    call_inbound: RetellInboundCallResponseData


class RetellLifecycleCall(BaseModel):
    call_id: str
    call_status: str | None = None
    direction: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    disconnection_reason: str | None = None
    transcript: str | None = None


class RetellLifecycleWebhookPayload(BaseModel):
    event: str
    call: RetellLifecycleCall


class RetellTranscriptUtterance(BaseModel):
    role: str | None = None
    content: str | None = None


class RetellRealtimeCall(BaseModel):
    call_id: str
    call_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetellCallDetailsEvent(BaseModel):
    interaction_type: Literal["call_details"]
    call: RetellRealtimeCall


class RetellUpdateOnlyEvent(BaseModel):
    interaction_type: Literal["update_only"]
    transcript: list[RetellTranscriptUtterance] = Field(default_factory=list)
    turntaking: str | None = None


class RetellPingPongEvent(BaseModel):
    interaction_type: Literal["ping_pong"]
    timestamp: int | None = None


class RetellResponseRequiredEvent(BaseModel):
    interaction_type: Literal["response_required"]
    response_id: int
    transcript: list[RetellTranscriptUtterance] = Field(default_factory=list)


class RetellReminderRequiredEvent(BaseModel):
    interaction_type: Literal["reminder_required"]
    response_id: int
    transcript: list[RetellTranscriptUtterance] = Field(default_factory=list)


RetellWebsocketEvent = Annotated[
    RetellCallDetailsEvent
    | RetellUpdateOnlyEvent
    | RetellPingPongEvent
    | RetellResponseRequiredEvent
    | RetellReminderRequiredEvent,
    Field(discriminator="interaction_type"),
]

_RETELL_WEBSOCKET_EVENT_ADAPTER = TypeAdapter(RetellWebsocketEvent)


def parse_retell_websocket_event(payload: dict[str, Any]) -> RetellWebsocketEvent:
    return _RETELL_WEBSOCKET_EVENT_ADAPTER.validate_python(payload)

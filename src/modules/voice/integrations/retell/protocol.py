from __future__ import annotations

from enum import StrEnum
import time
from typing import Any


class RetellInteractionType(StrEnum):
    CALL_DETAILS = "call_details"
    UPDATE_ONLY = "update_only"
    PING_PONG = "ping_pong"
    RESPONSE_REQUIRED = "response_required"
    REMINDER_REQUIRED = "reminder_required"


class RetellResponseType(StrEnum):
    CONFIG = "config"
    PING_PONG = "ping_pong"
    RESPONSE = "response"


def build_initial_events() -> list[dict[str, Any]]:
    """Return the initial websocket events Retell expects from us.

    Retell websocket protocol docs:
    https://docs.retellai.com/api-references/llm-websocket

    Retell tells us what kind of realtime event we are receiving through
    `interaction_type`. The ones we handle today are `call_details`,
    `update_only`, `ping_pong`, `response_required`, and `reminder_required`.
    """
    return [
        {
            "response_type": RetellResponseType.CONFIG,
            "config": {
                "auto_reconnect": True,
                "call_details": True,
                "transcript_with_tool_calls": False,
            },
        }
    ]


def build_ping_event() -> dict[str, Any]:
    return {
        "response_type": RetellResponseType.PING_PONG,
        "timestamp": int(time.time() * 1000),
    }


def build_response_event(
    *,
    response_id: int,
    content: str,
    end_call: bool,
    content_complete: bool = True,
) -> dict[str, Any]:
    return {
        "response_type": RetellResponseType.RESPONSE,
        "response_id": response_id,
        "content": content,
        "content_complete": content_complete,
        "end_call": end_call,
    }

from __future__ import annotations

import hashlib
from typing import Any

from src.core.constants import CHANNEL_VOICE_CALL
from src.core.utils import deep_merge_dicts
from src.modules.conversations.metadata import build_message_metadata
from src.modules.conversations.model import ConversationMessage
from src.modules.conversations.repository import ConversationRepository


def build_begin_message_fingerprint(content: str) -> str:
    return _fingerprint_text(seed="begin", text=content, index=0)


def build_utterance_fingerprint(text: str, index: int) -> str:
    return _fingerprint_text(seed=text, text=text, index=index)


def build_voice_message_metadata(
    *,
    settings: Any,
    message_type: str,
    provider: str,
    call_id: str | None,
    provider_event_type: str,
    provider_response_id: int | None = None,
    utterance_fingerprint: str | None = None,
    parent_utterance_fingerprint: str | None = None,
    begin_message: bool = False,
) -> dict[str, Any]:
    return deep_merge_dicts(
        build_message_metadata(
            settings=settings,
            message_type=message_type,
        ),
        {
            "voice": build_voice_metadata(
                provider=provider,
                call_id=call_id,
                provider_event_type=provider_event_type,
                provider_response_id=provider_response_id,
                utterance_fingerprint=utterance_fingerprint,
                parent_utterance_fingerprint=parent_utterance_fingerprint,
                begin_message=begin_message,
            )
        },
    )


async def find_begin_message(
    repository: ConversationRepository,
    conversation_id: str,
) -> ConversationMessage | None:
    messages = await repository.list_messages(conversation_id)
    for message in messages:
        voice_metadata = (message.message_metadata or {}).get("voice") or {}
        if voice_metadata.get("begin_message"):
            return message
    return None


async def find_agent_message_for_fingerprint(
    repository: ConversationRepository,
    conversation_id: str,
    utterance_fingerprint: str,
) -> ConversationMessage | None:
    messages = await repository.list_messages(conversation_id)
    for message in reversed(messages):
        voice_metadata = (message.message_metadata or {}).get("voice") or {}
        if voice_metadata.get("parent_utterance_fingerprint") == utterance_fingerprint:
            return message
    return None


async def get_existing_response_text(
    repository: ConversationRepository,
    conversation_id: str,
    utterance_fingerprint: str,
) -> str | None:
    message = await find_agent_message_for_fingerprint(
        repository,
        conversation_id,
        utterance_fingerprint,
    )
    return message.content if message is not None else None


async def get_existing_response_message_id(
    repository: ConversationRepository,
    conversation_id: str,
    utterance_fingerprint: str,
) -> str | None:
    message = await find_agent_message_for_fingerprint(
        repository,
        conversation_id,
        utterance_fingerprint,
    )
    return message.id if message is not None else None


def build_voice_metadata(
    *,
    provider: str,
    call_id: str | None,
    provider_event_type: str,
    provider_response_id: int | None,
    utterance_fingerprint: str | None,
    parent_utterance_fingerprint: str | None,
    begin_message: bool,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "source_channel": CHANNEL_VOICE_CALL,
        "provider": provider,
        "provider_event_type": provider_event_type,
        "begin_message": begin_message,
    }
    if call_id is not None:
        metadata["provider_call_id"] = call_id
    if provider_response_id is not None:
        metadata["provider_response_id"] = provider_response_id
    if utterance_fingerprint is not None:
        metadata["utterance_fingerprint"] = utterance_fingerprint
    if parent_utterance_fingerprint is not None:
        metadata["parent_utterance_fingerprint"] = parent_utterance_fingerprint
    return metadata


def _fingerprint_text(
    *,
    seed: str,
    text: str,
    index: int,
) -> str:
    normalized_text = " ".join(text.strip().lower().split())
    digest = hashlib.sha256(f"{seed}:{index}:{normalized_text}".encode("utf-8"))
    return digest.hexdigest()

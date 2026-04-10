from __future__ import annotations

from fastapi import Depends

from src.core.config import Settings, get_settings
from src.modules.voice.dependencies import (
    get_voice_conversation_service,
    get_voice_session_store,
)
from src.modules.voice.integrations.retell.adapter import RetellAdapter
from src.modules.voice.service import VoiceConversationService
from src.modules.voice.session_store import VoiceSessionStore


def get_retell_adapter(
    voice_service: VoiceConversationService = Depends(get_voice_conversation_service),
    session_store: VoiceSessionStore = Depends(get_voice_session_store),
    settings: Settings = Depends(get_settings),
) -> RetellAdapter:
    return RetellAdapter(
        voice_service=voice_service,
        session_store=session_store,
        settings=settings,
    )

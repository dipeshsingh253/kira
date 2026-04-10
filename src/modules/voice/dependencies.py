from __future__ import annotations

from functools import lru_cache

from fastapi import Depends
from redis.asyncio import Redis

from src.core.config import get_settings
from src.modules.conversations.dependencies import get_conversation_service
from src.modules.conversations.service import ConversationService
from src.modules.profiles.repository import ProfileRepository, get_profile_repository
from src.modules.voice.metrics import VoiceMetrics
from src.modules.voice.service import VoiceConversationService
from src.modules.voice.session_store import RedisVoiceSessionStore, VoiceSessionStore


@lru_cache
def _get_voice_session_redis_client() -> Redis:
    settings = get_settings()
    return Redis.from_url(settings.redis_url, decode_responses=True)


@lru_cache
def _get_voice_session_store_singleton() -> VoiceSessionStore:
    settings = get_settings()
    return RedisVoiceSessionStore(
        redis=_get_voice_session_redis_client(),
        key_prefix=settings.voice_session_redis_prefix,
        ttl_seconds=settings.voice_session_ttl_seconds,
    )


def get_voice_session_store() -> VoiceSessionStore:
    return _get_voice_session_store_singleton()


@lru_cache
def get_voice_metrics() -> VoiceMetrics:
    return VoiceMetrics()


def get_voice_conversation_service(
    conversation_service: ConversationService = Depends(get_conversation_service),
    profile_repository: ProfileRepository = Depends(get_profile_repository),
    session_store: VoiceSessionStore = Depends(get_voice_session_store),
    metrics: VoiceMetrics = Depends(get_voice_metrics),
) -> VoiceConversationService:
    return VoiceConversationService(
        conversation_service=conversation_service,
        profile_repository=profile_repository,
        session_store=session_store,
        metrics=metrics,
    )


async def close_voice_dependencies() -> None:
    store = _get_voice_session_store_singleton()
    await store.close()
    _get_voice_session_store_singleton.cache_clear()
    _get_voice_session_redis_client.cache_clear()
    get_voice_metrics.cache_clear()

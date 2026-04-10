from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone

from redis.asyncio import Redis

from src.modules.voice.schemas import VoiceHealthStatus, VoiceSessionRecord


class VoiceSessionStore(ABC):
    @abstractmethod
    async def create_session(self, session: VoiceSessionRecord) -> VoiceSessionRecord:
        raise NotImplementedError

    @abstractmethod
    async def save_session(self, session: VoiceSessionRecord) -> VoiceSessionRecord:
        raise NotImplementedError

    @abstractmethod
    async def get_session_by_conversation_id(
        self,
        conversation_id: str,
    ) -> VoiceSessionRecord | None:
        raise NotImplementedError

    @abstractmethod
    async def get_session_by_inbound_fingerprint(
        self,
        provider: str,
        inbound_fingerprint: str,
    ) -> VoiceSessionRecord | None:
        raise NotImplementedError

    @abstractmethod
    async def get_session_by_call_id(
        self,
        provider: str,
        call_id: str,
    ) -> VoiceSessionRecord | None:
        raise NotImplementedError

    @abstractmethod
    async def bind_call_id(
        self,
        *,
        conversation_id: str,
        provider: str,
        call_id: str,
    ) -> VoiceSessionRecord | None:
        raise NotImplementedError

    @abstractmethod
    async def check_health(self) -> VoiceHealthStatus:
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        raise NotImplementedError


class InMemoryVoiceSessionStore(VoiceSessionStore):
    def __init__(self) -> None:
        self._sessions_by_conversation: dict[str, VoiceSessionRecord] = {}
        self._conversation_by_inbound: dict[tuple[str, str], str] = {}
        self._conversation_by_call: dict[tuple[str, str], str] = {}

    async def create_session(self, session: VoiceSessionRecord) -> VoiceSessionRecord:
        existing_conversation_id = self._conversation_by_inbound.get(
            (session.provider, session.inbound_fingerprint)
        )
        if existing_conversation_id is not None:
            return self._sessions_by_conversation[existing_conversation_id]

        self._sessions_by_conversation[session.conversation_id] = session
        self._conversation_by_inbound[(session.provider, session.inbound_fingerprint)] = (
            session.conversation_id
        )
        return session

    async def save_session(self, session: VoiceSessionRecord) -> VoiceSessionRecord:
        session.updated_at = datetime.now(timezone.utc)
        self._sessions_by_conversation[session.conversation_id] = session
        self._conversation_by_inbound[(session.provider, session.inbound_fingerprint)] = (
            session.conversation_id
        )
        if session.provider_call_id is not None:
            self._conversation_by_call[(session.provider, session.provider_call_id)] = (
                session.conversation_id
            )
        return session

    async def get_session_by_conversation_id(
        self,
        conversation_id: str,
    ) -> VoiceSessionRecord | None:
        return self._sessions_by_conversation.get(conversation_id)

    async def get_session_by_inbound_fingerprint(
        self,
        provider: str,
        inbound_fingerprint: str,
    ) -> VoiceSessionRecord | None:
        conversation_id = self._conversation_by_inbound.get((provider, inbound_fingerprint))
        if conversation_id is None:
            return None
        return self._sessions_by_conversation.get(conversation_id)

    async def get_session_by_call_id(
        self,
        provider: str,
        call_id: str,
    ) -> VoiceSessionRecord | None:
        conversation_id = self._conversation_by_call.get((provider, call_id))
        if conversation_id is None:
            return None
        return self._sessions_by_conversation.get(conversation_id)

    async def bind_call_id(
        self,
        *,
        conversation_id: str,
        provider: str,
        call_id: str,
    ) -> VoiceSessionRecord | None:
        session = self._sessions_by_conversation.get(conversation_id)
        if session is None:
            return None
        session.provider_call_id = call_id
        session.status = "active"
        await self.save_session(session)
        return session

    async def check_health(self) -> VoiceHealthStatus:
        return VoiceHealthStatus(
            status="healthy",
            backend="in_memory",
            details={"active_sessions": len(self._sessions_by_conversation)},
        )

    async def close(self) -> None:
        self._sessions_by_conversation.clear()
        self._conversation_by_inbound.clear()
        self._conversation_by_call.clear()


class RedisVoiceSessionStore(VoiceSessionStore):
    def __init__(
        self,
        *,
        redis: Redis,
        key_prefix: str,
        ttl_seconds: int,
    ) -> None:
        self.redis = redis
        self.key_prefix = key_prefix.rstrip(":")
        self.ttl_seconds = ttl_seconds

    def _session_key(self, conversation_id: str) -> str:
        return f"{self.key_prefix}:session:{conversation_id}"

    def _inbound_key(self, provider: str, inbound_fingerprint: str) -> str:
        return f"{self.key_prefix}:inbound:{provider}:{inbound_fingerprint}"

    def _call_key(self, provider: str, call_id: str) -> str:
        return f"{self.key_prefix}:call:{provider}:{call_id}"

    async def create_session(self, session: VoiceSessionRecord) -> VoiceSessionRecord:
        existing = await self.get_session_by_inbound_fingerprint(
            session.provider,
            session.inbound_fingerprint,
        )
        if existing is not None:
            return existing

        inbound_key = self._inbound_key(session.provider, session.inbound_fingerprint)
        claimed = await self.redis.set(
            inbound_key,
            session.conversation_id,
            ex=self.ttl_seconds,
            nx=True,
        )
        if not claimed:
            existing = await self.get_session_by_inbound_fingerprint(
                session.provider,
                session.inbound_fingerprint,
            )
            if existing is not None:
                return existing

        await self.save_session(session)
        return session

    async def save_session(self, session: VoiceSessionRecord) -> VoiceSessionRecord:
        session.updated_at = datetime.now(timezone.utc)
        pipeline = self.redis.pipeline()
        pipeline.set(
            self._session_key(session.conversation_id),
            session.model_dump_json(),
            ex=self.ttl_seconds,
        )
        pipeline.set(
            self._inbound_key(session.provider, session.inbound_fingerprint),
            session.conversation_id,
            ex=self.ttl_seconds,
        )
        if session.provider_call_id is not None:
            pipeline.set(
                self._call_key(session.provider, session.provider_call_id),
                session.conversation_id,
                ex=self.ttl_seconds,
            )
        await pipeline.execute()
        return session

    async def get_session_by_conversation_id(
        self,
        conversation_id: str,
    ) -> VoiceSessionRecord | None:
        payload = await self.redis.get(self._session_key(conversation_id))
        if payload is None:
            return None
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        return VoiceSessionRecord.model_validate_json(payload)

    async def get_session_by_inbound_fingerprint(
        self,
        provider: str,
        inbound_fingerprint: str,
    ) -> VoiceSessionRecord | None:
        conversation_id = await self.redis.get(self._inbound_key(provider, inbound_fingerprint))
        if conversation_id is None:
            return None
        if isinstance(conversation_id, bytes):
            conversation_id = conversation_id.decode("utf-8")
        return await self.get_session_by_conversation_id(conversation_id)

    async def get_session_by_call_id(
        self,
        provider: str,
        call_id: str,
    ) -> VoiceSessionRecord | None:
        conversation_id = await self.redis.get(self._call_key(provider, call_id))
        if conversation_id is None:
            return None
        if isinstance(conversation_id, bytes):
            conversation_id = conversation_id.decode("utf-8")
        return await self.get_session_by_conversation_id(conversation_id)

    async def bind_call_id(
        self,
        *,
        conversation_id: str,
        provider: str,
        call_id: str,
    ) -> VoiceSessionRecord | None:
        session = await self.get_session_by_conversation_id(conversation_id)
        if session is None:
            return None
        session.provider_call_id = call_id
        session.status = "active"
        await self.save_session(session)
        return session

    async def check_health(self) -> VoiceHealthStatus:
        try:
            pong = await self.redis.ping()
        except Exception as exc:  # pragma: no cover - defensive path
            return VoiceHealthStatus(
                status="unhealthy",
                backend="redis",
                details={"error": str(exc)},
            )

        return VoiceHealthStatus(
            status="healthy" if pong else "unhealthy",
            backend="redis",
            details={"ping": bool(pong)},
        )

    async def close(self) -> None:
        await self.redis.aclose()

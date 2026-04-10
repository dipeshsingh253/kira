from __future__ import annotations

from time import perf_counter

from fastapi import HTTPException, status
from loguru import logger

from src.core.constants import (
    CHANNEL_VOICE_CALL,
    CONVERSATION_MESSAGE_TYPE_AGENT_ANSWER,
    CONVERSATION_MESSAGE_TYPE_GREETING,
    CONVERSATION_MESSAGE_TYPE_PARENT_QUERY,
    CONVERSATION_STATUS_COMPLETED,
    CONVERSATION_STATUS_FAILED,
    MESSAGE_ROLE_USER,
)
from src.modules.conversations.model import ConversationMessage
from src.modules.conversations.service import ConversationService
from src.modules.profiles.repository import ProfileRepository
from src.modules.voice.message_utils import (
    build_begin_message_fingerprint,
    build_utterance_fingerprint,
    build_voice_message_metadata,
    build_voice_metadata,
    find_begin_message,
    get_existing_response_message_id,
    get_existing_response_text,
)
from src.modules.voice.metrics import VoiceMetrics
from src.modules.voice.schemas import (
    VoiceInboundDecision,
    VoiceSessionRecord,
    VoiceTurnResult,
)
from src.modules.voice.session_store import VoiceSessionStore


class VoiceConversationService:
    def __init__(
        self,
        *,
        conversation_service: ConversationService,
        profile_repository: ProfileRepository,
        session_store: VoiceSessionStore,
        metrics: VoiceMetrics,
    ) -> None:
        self.conversation_service = conversation_service
        self.profile_repository = profile_repository
        self.session_store = session_store
        self.metrics = metrics

    async def accept_inbound_call(
        self,
        *,
        caller_phone: str,
        provider: str,
        inbound_fingerprint: str,
    ) -> VoiceInboundDecision:
        """Decide whether an inbound caller should be allowed into the voice flow.

        We first check whether this webhook is just a retry of one we already handled.
        If not, we look up the caller by phone number. Known callers get a Kira voice
        conversation plus a live session record. Unknown callers are rejected.

        Notes:
        - This service is provider-neutral even though Retell is the first caller.
        - Rejecting the caller here means we do not create any conversation rows.
        """
        existing_session = await self.session_store.get_session_by_inbound_fingerprint(
            provider,
            inbound_fingerprint,
        )
        if existing_session is not None:
            return VoiceInboundDecision.accepted_call(
                conversation_id=existing_session.conversation_id,
                parent_id=existing_session.parent_id,
                parent_phone=existing_session.parent_phone,
            )

        parent_profile = self.profile_repository.get_parent_profile_by_phone(caller_phone)
        if parent_profile is None:
            self.metrics.increment("rejected_calls")
            logger.info(
                "Rejected inbound voice call for unknown caller {} via {}",
                caller_phone,
                provider,
            )
            return VoiceInboundDecision.rejected_call()

        bootstrap = await self.conversation_service.create_conversation_for_parent(
            parent_profile,
            channel=CHANNEL_VOICE_CALL,
            persist_greeting=False,
        )
        session = VoiceSessionRecord(
            conversation_id=bootstrap.conversation.id,
            parent_id=parent_profile.parent_id,
            parent_phone=parent_profile.parent.phone,
            provider=provider,
            inbound_fingerprint=inbound_fingerprint,
        )
        stored_session = await self.session_store.create_session(session)
        self.metrics.increment("accepted_calls")
        logger.info(
            "Accepted inbound voice call conversation={} parent={} provider={}",
            stored_session.conversation_id,
            stored_session.parent_id,
            provider,
        )
        return VoiceInboundDecision.accepted_call(
            conversation_id=stored_session.conversation_id,
            parent_id=stored_session.parent_id,
            parent_phone=stored_session.parent_phone,
        )

    async def bind_provider_call(
        self,
        *,
        conversation_id: str,
        provider: str,
        call_id: str,
    ) -> VoiceSessionRecord:
        """Attach the provider call id to the stored voice session."""
        session = await self.session_store.bind_call_id(
            conversation_id=conversation_id,
            provider=provider,
            call_id=call_id,
        )
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Voice session not found for call binding",
            )
        logger.info(
            "Bound voice session conversation={} call_id={} provider={}",
            conversation_id,
            call_id,
            provider,
        )
        return session

    async def persist_begin_message(
        self,
        *,
        conversation_id: str,
        provider: str,
        call_id: str | None,
        content: str,
    ) -> ConversationMessage:
        """Save the opening greeting for the call, but only once.

        The greeting is stored as a normal agent message so the transcript shows
        exactly what the caller heard. We check both session state and the DB so a
        reconnect does not duplicate the greeting.

        Notes:
        - This method is intentionally idempotent.
        - The greeting gets a dedicated metadata flag so it is easy to find later.
        """
        session = await self._require_session(conversation_id)
        existing_message = await find_begin_message(
            self.conversation_service.conversation_repository,
            conversation_id,
        )
        if existing_message is not None:
            if not session.greeting_persisted:
                session.greeting_persisted = True
                await self.session_store.save_session(session)
            return existing_message

        message = await self.conversation_service.persist_agent_message(
            conversation_id,
            content=content,
            message_type=CONVERSATION_MESSAGE_TYPE_GREETING,
            metadata_extra=build_voice_message_metadata(
                settings=self.conversation_service.settings,
                message_type=CONVERSATION_MESSAGE_TYPE_GREETING,
                provider=provider,
                call_id=call_id,
                provider_event_type="begin_message",
                begin_message=True,
                utterance_fingerprint=build_begin_message_fingerprint(content),
            ),
        )
        await self.conversation_service.conversation_repository.commit()

        session.greeting_persisted = True
        await self.session_store.save_session(session)
        return message

    async def handle_live_turn(
        self,
        *,
        conversation_id: str,
        provider: str,
        call_id: str | None,
        response_id: int,
        utterance_text: str,
        utterance_index: int,
        provider_event_type: str = "response_required",
    ) -> VoiceTurnResult:
        """Handle a normal live voice turn from caller speech to agent answer.

        We dedupe retries, save the caller utterance with voice metadata, run the
        shared Kira answer flow, and cache the result in session state so repeated
        Retell events do not create duplicate messages.

        Notes:
        - If Retell repeats the same turn, we return the cached answer instead of generating again.
        - A successful answer resets the follow-up reminder state for the call.
        """
        session = await self._require_session(conversation_id)
        utterance_fingerprint = build_utterance_fingerprint(
            utterance_text,
            utterance_index,
        )

        cached_turn = await self._get_cached_turn_result(
            session=session,
            conversation_id=conversation_id,
            utterance_fingerprint=utterance_fingerprint,
            response_id=response_id,
        )
        if cached_turn is not None:
            return cached_turn

        session.latest_response_id = response_id
        await self.session_store.save_session(session)

        started_at = perf_counter()
        turn = await self.conversation_service.process_parent_turn(
            conversation_id,
            message=utterance_text,
            user_message_metadata_extra={"voice": build_voice_metadata(
                provider=provider,
                call_id=call_id,
                provider_event_type=provider_event_type,
                provider_response_id=response_id,
                utterance_fingerprint=utterance_fingerprint,
                parent_utterance_fingerprint=None,
                begin_message=False,
            )},
            agent_message_metadata_extra={"voice": build_voice_metadata(
                provider=provider,
                call_id=call_id,
                provider_event_type="response",
                provider_response_id=response_id,
                utterance_fingerprint=utterance_fingerprint,
                parent_utterance_fingerprint=utterance_fingerprint,
                begin_message=False,
            )},
        )
        duration_ms = round((perf_counter() - started_at) * 1000, 2)
        self.metrics.increment("voice_turns")
        self.metrics.record_generation_latency(duration_ms)

        await self._save_successful_turn(
            session=session,
            response_id=response_id,
            utterance_fingerprint=utterance_fingerprint,
            agent_message_id=turn.agent_message.id,
            agent_response_text=turn.agent_result.response_text,
        )

        logger.info(
            "Handled voice turn conversation={} call_id={} response_id={} provider={}",
            conversation_id,
            call_id,
            response_id,
            provider,
        )
        return VoiceTurnResult(
            conversation_id=conversation_id,
            agent_message_id=turn.agent_message.id,
            agent_response_text=turn.agent_result.response_text,
            cached=False,
        )

    async def handle_scripted_turn(
        self,
        *,
        conversation_id: str,
        provider: str,
        call_id: str | None,
        response_id: int,
        utterance_text: str,
        utterance_index: int,
        agent_response_text: str,
        provider_event_type: str,
    ) -> VoiceTurnResult:
        """Handle a caller turn where we already know the reply and do not need the model.

        This is used for simple voice-only flows like "no thanks" where a scripted
        answer is clearer, cheaper, and faster than calling the model again.

        Notes:
        - We still save both sides of the turn so the transcript stays complete.
        - Duplicate scripted turns use the same dedupe logic as normal turns.
        """
        session = await self._require_session(conversation_id)
        utterance_fingerprint = build_utterance_fingerprint(
            utterance_text,
            utterance_index,
        )

        cached_turn = await self._get_cached_turn_result(
            session=session,
            conversation_id=conversation_id,
            utterance_fingerprint=utterance_fingerprint,
            response_id=response_id,
        )
        if cached_turn is not None:
            return cached_turn

        await self.conversation_service.conversation_repository.create_message(
            conversation_id=conversation_id,
            role=MESSAGE_ROLE_USER,
            content=utterance_text,
            message_metadata=build_voice_message_metadata(
                settings=self.conversation_service.settings,
                message_type=CONVERSATION_MESSAGE_TYPE_PARENT_QUERY,
                provider=provider,
                call_id=call_id,
                provider_event_type=provider_event_type,
                provider_response_id=response_id,
                utterance_fingerprint=utterance_fingerprint,
            ),
        )

        agent_message = await self.conversation_service.persist_agent_message(
            conversation_id,
            content=agent_response_text,
            message_type=CONVERSATION_MESSAGE_TYPE_AGENT_ANSWER,
            metadata_extra=build_voice_message_metadata(
                settings=self.conversation_service.settings,
                message_type=CONVERSATION_MESSAGE_TYPE_AGENT_ANSWER,
                provider=provider,
                call_id=call_id,
                provider_event_type="response",
                provider_response_id=response_id,
                utterance_fingerprint=utterance_fingerprint,
                parent_utterance_fingerprint=utterance_fingerprint,
            ),
        )
        await self.conversation_service.conversation_repository.commit()

        await self._save_successful_turn(
            session=session,
            response_id=response_id,
            utterance_fingerprint=utterance_fingerprint,
            agent_message_id=agent_message.id,
            agent_response_text=agent_response_text,
        )

        logger.info(
            "Handled scripted voice turn conversation={} call_id={} response_id={} provider={}",
            conversation_id,
            call_id,
            response_id,
            provider,
        )
        return VoiceTurnResult(
            conversation_id=conversation_id,
            agent_message_id=agent_message.id,
            agent_response_text=agent_response_text,
            cached=False,
        )

    async def persist_scripted_agent_message(
        self,
        *,
        conversation_id: str,
        provider: str,
        call_id: str | None,
        content: str,
        provider_event_type: str,
        provider_response_id: int | None = None,
    ) -> ConversationMessage:
        """Save a standalone scripted agent line that is not tied to a new user turn.

        This is mainly for reminder prompts and farewells. The caller hears a scripted
        line, and we save that same line to the transcript so the DB matches the call.

        Notes:
        - We still attach normal voice metadata so debugging stays consistent.
        - Session state is updated because follow-up logic needs to know the last thing we said.
        """
        session = await self._require_session(conversation_id)
        message = await self.conversation_service.persist_agent_message(
            conversation_id,
            content=content,
            message_type=CONVERSATION_MESSAGE_TYPE_AGENT_ANSWER,
            metadata_extra=build_voice_message_metadata(
                settings=self.conversation_service.settings,
                message_type=CONVERSATION_MESSAGE_TYPE_AGENT_ANSWER,
                provider=provider,
                call_id=call_id,
                provider_event_type=provider_event_type,
                provider_response_id=provider_response_id,
            ),
        )
        await self.conversation_service.conversation_repository.commit()

        session.last_agent_message_id = message.id
        session.last_agent_response_text = content
        if provider_response_id is not None:
            session.latest_response_id = provider_response_id
            session.last_processed_response_id = provider_response_id
        await self.session_store.save_session(session)
        return message

    async def complete_call(
        self,
        *,
        conversation_id: str,
        failed: bool = False,
    ) -> None:
        """Mark the call finished in both the conversation row and the live session state."""
        await self.conversation_service.update_conversation_status(
            conversation_id,
            new_status=CONVERSATION_STATUS_FAILED if failed else CONVERSATION_STATUS_COMPLETED,
        )
        session = await self.session_store.get_session_by_conversation_id(conversation_id)
        if session is not None:
            session.status = "failed" if failed else "completed"
            await self.session_store.save_session(session)
        if failed:
            self.metrics.increment("failed_calls")

    async def fail_call(
        self,
        *,
        conversation_id: str,
    ) -> None:
        self.metrics.increment("fallback_responses")
        await self.complete_call(conversation_id=conversation_id, failed=True)

    async def _require_session(self, conversation_id: str) -> VoiceSessionRecord:
        session = await self.session_store.get_session_by_conversation_id(conversation_id)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Voice session not found",
            )
        return session

    async def _get_cached_turn_result(
        self,
        *,
        session: VoiceSessionRecord,
        conversation_id: str,
        utterance_fingerprint: str,
        response_id: int,
    ) -> VoiceTurnResult | None:
        is_same_turn = session.last_processed_user_fingerprint == utterance_fingerprint
        is_stale_response = (
            session.latest_response_id is not None
            and response_id < session.latest_response_id
        )
        if not is_same_turn and not is_stale_response:
            return None

        repository = self.conversation_service.conversation_repository
        cached_response = session.last_agent_response_text or await get_existing_response_text(
            repository,
            conversation_id,
            utterance_fingerprint,
        )
        cached_message_id = session.last_agent_message_id or await get_existing_response_message_id(
            repository,
            conversation_id,
            utterance_fingerprint,
        )
        if not cached_response or not cached_message_id:
            return None

        return VoiceTurnResult(
            conversation_id=conversation_id,
            agent_message_id=cached_message_id,
            agent_response_text=cached_response,
            cached=True,
        )

    async def _save_successful_turn(
        self,
        *,
        session: VoiceSessionRecord,
        response_id: int,
        utterance_fingerprint: str,
        agent_message_id: str,
        agent_response_text: str,
    ) -> None:
        session.latest_response_id = response_id
        session.last_processed_response_id = response_id
        session.last_processed_user_fingerprint = utterance_fingerprint
        session.last_agent_message_id = agent_message_id
        session.last_agent_response_text = agent_response_text
        session.follow_up_prompt_count = 0
        await self.session_store.save_session(session)

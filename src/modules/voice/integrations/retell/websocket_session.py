from __future__ import annotations

import asyncio
import json

from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger
from pydantic import ValidationError

from src.core.config import Settings
from src.modules.voice.integrations.retell.protocol import (
    RetellInteractionType,
    build_initial_events,
    build_ping_event,
    build_response_event,
)
from src.modules.voice.integrations.retell.schemas import (
    RetellCallDetailsEvent,
    RetellPingPongEvent,
    RetellReminderRequiredEvent,
    RetellResponseRequiredEvent,
    RetellUpdateOnlyEvent,
    RetellWebsocketEvent,
    parse_retell_websocket_event,
)
from src.modules.voice.policies import (
    CALL_NOT_READY_MESSAGE,
    FAREWELL_MESSAGE,
    FOLLOW_UP_PROMPT,
    REPEAT_PROMPT_MESSAGE,
    RUNTIME_ERROR_MESSAGE,
    SILENCE_FAREWELL_MESSAGE,
    UNKNOWN_CALLER_MESSAGE,
    WEB_CALL_PROBE_MESSAGE,
    build_progress_message,
    is_close_intent,
)
from src.modules.voice.schemas import VoiceSessionRecord
from src.modules.voice.service import VoiceConversationService
from src.modules.voice.session_store import VoiceSessionStore


class RetellWebsocketSession:
    _MISSING_CONVERSATION_ID_MESSAGE = (
        "Retell call details did not include conversation_id metadata. "
        "This usually means the session did not come through the inbound-call "
        "acceptance flow, or you are using the agent web-call test instead of "
        "a phone-number inbound call."
    )

    def __init__(
        self,
        *,
        websocket: WebSocket,
        call_id: str,
        voice_service: VoiceConversationService,
        session_store: VoiceSessionStore,
        settings: Settings,
    ) -> None:
        self.websocket = websocket
        self.call_id = call_id
        self.voice_service = voice_service
        self.session_store = session_store
        self.settings = settings
        self.stop_event = asyncio.Event()
        self.ping_task: asyncio.Task[None] | None = None

    async def run(self) -> None:
        """Run one live Retell websocket session from connect to cleanup.

        This owns the full realtime loop: accept the socket, send the initial
        config, dispatch incoming Retell events, and cleanly stop the heartbeat
        task when the call ends.

        Notes:
        - The router should only delegate to this class and not keep protocol branching of its own.
        - Retell closes sockets as part of normal call shutdown, so disconnects are not treated as errors.
        """
        await self.websocket.accept()
        self.ping_task = asyncio.create_task(self._ping_loop())

        try:
            await self._send_initial_events()

            while True:
                event = await self._receive_event()
                if event is None:
                    continue

                should_continue = await self._dispatch_event(event)
                if not should_continue:
                    return
        except WebSocketDisconnect:
            return
        finally:
            await self.shutdown_session()

    async def _send_initial_events(self) -> None:
        """Send the config event Retell expects right after the websocket opens.

        This is where we tell Retell how to run the session on its side. In our
        case we ask Retell to:
        - auto reconnect and keep the socket alive with ping/pong
        - send `call_details` immediately so we can bind the call to Kira
        - skip `transcript_with_tool_calls` because we are not using that flow yet

        Docs: https://docs.retellai.com/api-references/llm-websocket
        """
        for event in build_initial_events():
            await self.websocket.send_json(event)

    async def _receive_event(self) -> RetellWebsocketEvent | None:
        raw_payload = await self.websocket.receive_text()

        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError:
            logger.warning(
                "Ignoring malformed Retell websocket payload for call {}",
                self.call_id,
            )
            return None

        if not isinstance(payload, dict):
            logger.warning(
                "Ignoring non-object Retell websocket payload for call {}",
                self.call_id,
            )
            return None

        try:
            return parse_retell_websocket_event(payload)
        except ValidationError:
            interaction_type = payload.get("interaction_type")
            logger.info(
                "Ignoring unsupported Retell websocket event {} for call {}",
                interaction_type,
                self.call_id,
            )
            return None

    async def _dispatch_event(self, event: RetellWebsocketEvent) -> bool:
        """Route one typed Retell websocket event to the right handler.

        Retell event reference:
        https://docs.retellai.com/api-references/llm-websocket

        Event types we handle here:
        - `call_details`: the call metadata Retell sends after connect so we can bind this websocket to a Kira conversation
        - `update_only`: transcript / turn-taking updates that do not need the agent to say anything yet
        - `ping_pong`: heartbeat events used to keep the websocket alive
        - `response_required`: Retell wants the agent's actual response for the current user turn
        - `reminder_required`: Retell wants a follow-up line because the user has been silent for a while
        """
        if isinstance(event, RetellCallDetailsEvent):
            return await self.handle_call_details(event)
        if isinstance(event, RetellUpdateOnlyEvent):
            return await self.handle_update_only(event)
        if isinstance(event, RetellPingPongEvent):
            return await self.handle_ping_pong(event)
        if isinstance(event, RetellResponseRequiredEvent):
            return await self.handle_response_required(event)
        if isinstance(event, RetellReminderRequiredEvent):
            return await self.handle_reminder_required(event)
        return True

    async def handle_call_details(self, event: RetellCallDetailsEvent) -> bool:
        """Bind the websocket call to a Kira conversation once Retell sends call details."""
        metadata = event.call.metadata
        conversation_id = metadata.get("conversation_id")
        if not conversation_id:
            if metadata.get("special_case") == "unknown_caller":
                await self.websocket.send_json(
                    build_response_event(
                        response_id=0,
                        content=str(metadata.get("message") or UNKNOWN_CALLER_MESSAGE),
                        end_call=True,
                    )
                )
                return False
            if str(event.call.call_type or "").lower() == "web_call":
                await self.handle_web_call_probe()
                return False

            await self.websocket.send_json(
                build_response_event(
                    response_id=1,
                    content=self._MISSING_CONVERSATION_ID_MESSAGE,
                    end_call=True,
                )
            )
            await self.websocket.close(code=1008)
            return False

        should_send_begin_message = await self._bind_call_from_details(conversation_id)
        await self.send_begin_message_if_needed(should_send_begin_message)
        return True

    async def handle_update_only(self, event: RetellUpdateOnlyEvent) -> bool:
        """Ignore transcript-only updates that do not require Kira to speak yet."""
        return True

    async def handle_ping_pong(self, event: RetellPingPongEvent) -> bool:
        """Reply to Retell ping events while the call is still open."""
        await self.websocket.send_json(build_ping_event())
        return True

    async def handle_response_required(self, event: RetellResponseRequiredEvent) -> bool:
        """Handle the normal "user asked something, now agent must answer" path.

        Retell sends `response_required` when it has decided this is a good time
        for the agent to speak. Our job here is:
        - optionally send a quick progress line so the caller gets instant feedback
        - build the real answer for this `response_id`
        - send a fallback and mark the call failed if anything breaks mid-turn

        The quick ack still goes back as a normal Retell `response` chunk for the
        current `response_id`, because that keeps the final answer on the same
        response stream. We send that chunk before any DB or model work starts,
        then give the socket a tiny moment to flush so the caller consistently
        hears the acknowledgement before the full answer is ready.

        Docs: https://docs.retellai.com/api-references/llm-websocket
        https://docs.retellai.com/api-references/llm-websocket#your-server-%3E-retell-sample-events
        """
        if self._should_send_progress_response(event):
            await self.websocket.send_json(
                build_response_event(
                    response_id=event.response_id,
                    content=build_progress_message(event.response_id),
                    end_call=False,
                    content_complete=False,
                )
            )

        try:
            response_event = await self._build_response_required_event(event)
        except Exception:
            response_event = await self.send_fallback_and_fail_call(
                response_id=event.response_id,
            )

        await self.websocket.send_json(response_event)
        return True

    async def handle_reminder_required(self, event: RetellReminderRequiredEvent) -> bool:
        """Handle Retell's silence reminder flow for an active call."""
        try:
            response_event = await self._build_reminder_response(event)
        except Exception:
            response_event = await self.send_fallback_and_fail_call(
                response_id=event.response_id,
            )

        await self.websocket.send_json(response_event)
        return True

    async def handle_web_call_probe(self) -> None:
        """Return a simple spoken probe for Retell dashboard `web_call` tests."""
        await self.websocket.send_json(
            build_response_event(
                response_id=0,
                content=WEB_CALL_PROBE_MESSAGE,
                end_call=True,
            )
        )

    async def send_begin_message_if_needed(self, should_send_begin_message: bool) -> None:
        """Speak the greeting after binding the call, but only if this call still needs it."""
        if not should_send_begin_message:
            return

        await self.voice_service.persist_begin_message(
            conversation_id=(await self._get_bound_session()).conversation_id,
            provider="retell",
            call_id=self.call_id,
            content=self.settings.retell_default_begin_message,
        )
        await self.websocket.send_json(
            build_response_event(
                response_id=0,
                content=self.settings.retell_default_begin_message,
                end_call=False,
            )
        )

    async def send_fallback_and_fail_call(self, *, response_id: int) -> dict[str, object]:
        """Send a generic failure line and mark the stored call as failed if it was bound."""
        bound_session = await self._get_bound_session()
        if bound_session is not None:
            await self.voice_service.fail_call(
                conversation_id=bound_session.conversation_id,
            )
        return build_response_event(
            response_id=response_id,
            content=RUNTIME_ERROR_MESSAGE,
            end_call=True,
        )

    async def shutdown_session(self) -> None:
        """Stop background tasks for this websocket session without surfacing shutdown noise."""
        self.stop_event.set()
        if self.ping_task is None:
            return
        self.ping_task.cancel()
        try:
            await self.ping_task
        except (asyncio.CancelledError, WebSocketDisconnect, RuntimeError):
            pass

    async def _bind_call_from_details(self, conversation_id: str) -> bool:
        session = await self.session_store.get_session_by_conversation_id(conversation_id)
        should_send_begin_message = session is None or not session.greeting_persisted

        await self.voice_service.bind_provider_call(
            conversation_id=conversation_id,
            provider="retell",
            call_id=self.call_id,
        )
        return should_send_begin_message

    async def _build_response_required_event(
        self,
        event: RetellResponseRequiredEvent,
    ) -> dict[str, object]:
        session = await self._get_bound_session()
        if session is None:
            return build_response_event(
                response_id=event.response_id,
                content=CALL_NOT_READY_MESSAGE,
                end_call=True,
            )

        latest_user = self._extract_latest_user_utterance(event.transcript)
        if latest_user is None:
            return build_response_event(
                response_id=event.response_id,
                content=REPEAT_PROMPT_MESSAGE,
                end_call=False,
            )

        if is_close_intent(latest_user["content"]):
            turn = await self.voice_service.handle_scripted_turn(
                conversation_id=session.conversation_id,
                provider="retell",
                call_id=self.call_id,
                response_id=event.response_id,
                utterance_text=latest_user["content"],
                utterance_index=latest_user["index"],
                agent_response_text=FAREWELL_MESSAGE,
                provider_event_type="close_intent",
            )
            await self.voice_service.complete_call(
                conversation_id=session.conversation_id,
                failed=False,
            )
            return build_response_event(
                response_id=event.response_id,
                content=turn.agent_response_text,
                end_call=True,
            )

        turn = await self.voice_service.handle_live_turn(
            conversation_id=session.conversation_id,
            provider="retell",
            call_id=self.call_id,
            response_id=event.response_id,
            utterance_text=latest_user["content"],
            utterance_index=latest_user["index"],
            provider_event_type=RetellInteractionType.RESPONSE_REQUIRED,
        )
        return build_response_event(
            response_id=event.response_id,
            content=turn.agent_response_text,
            end_call=False,
        )

    async def _build_reminder_response(
        self,
        event: RetellReminderRequiredEvent,
    ) -> dict[str, object]:
        session = await self._get_bound_session()
        if session is None:
            return build_response_event(
                response_id=event.response_id,
                content=CALL_NOT_READY_MESSAGE,
                end_call=True,
            )

        if session.follow_up_prompt_count <= 0:
            await self.voice_service.persist_scripted_agent_message(
                conversation_id=session.conversation_id,
                provider="retell",
                call_id=self.call_id,
                content=FOLLOW_UP_PROMPT,
                provider_event_type="reminder_prompt",
                provider_response_id=event.response_id,
            )
            session.follow_up_prompt_count = 1
            await self.session_store.save_session(session)
            return build_response_event(
                response_id=event.response_id,
                content=FOLLOW_UP_PROMPT,
                end_call=False,
            )

        await self.voice_service.persist_scripted_agent_message(
            conversation_id=session.conversation_id,
            provider="retell",
            call_id=self.call_id,
            content=SILENCE_FAREWELL_MESSAGE,
            provider_event_type="call_farewell",
            provider_response_id=event.response_id,
        )
        session.follow_up_prompt_count = 0
        await self.session_store.save_session(session)
        await self.voice_service.complete_call(
            conversation_id=session.conversation_id,
            failed=False,
        )
        return build_response_event(
            response_id=event.response_id,
            content=SILENCE_FAREWELL_MESSAGE,
            end_call=True,
        )

    async def _get_bound_session(self) -> VoiceSessionRecord | None:
        return await self.session_store.get_session_by_call_id("retell", self.call_id)

    async def _ping_loop(self) -> None:
        while not self.stop_event.is_set():
            await asyncio.sleep(2)
            if self.stop_event.is_set():
                break
            try:
                await self.websocket.send_json(build_ping_event())
            except (RuntimeError, WebSocketDisconnect):
                return

    def _should_send_progress_response(
        self,
        event: RetellResponseRequiredEvent,
    ) -> bool:
        # We only send the quick "just a moment" filler for normal questions.
        # If the latest user line is actually a close intent like "no thanks",
        # we should skip the filler and move straight into the close flow.
        # Retell asks for this agent turn through `response_required`.
        # Docs: https://docs.retellai.com/api-references/llm-websocket
        latest_user = self._extract_latest_user_utterance(event.transcript)
        if latest_user is None:
            return False
        return not is_close_intent(latest_user["content"])

    def _extract_latest_user_utterance(
        self,
        transcript: list,
    ) -> dict[str, object] | None:
        # Retell gives us the full transcript each time, so we walk backwards to
        # find the newest real user utterance instead of re-scanning from the top.
        # We return both the text and its transcript index because downstream code
        # uses the text for intent checks and the index for stable turn tracking.
        # Docs: https://docs.retellai.com/api-references/llm-websocket
        for index in range(len(transcript) - 1, -1, -1):
            utterance = transcript[index]
            role = str(utterance.role or "").lower()
            content = str(utterance.content or "").strip()
            if role != "user" or not content:
                continue
            return {"index": index, "content": content}
        return None

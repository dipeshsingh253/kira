from __future__ import annotations

import hashlib
import json

from fastapi import HTTPException, WebSocket, status
from loguru import logger

from src.core.config import Settings
from src.core.constants import CONVERSATION_STATUS_ACTIVE
from src.modules.voice.integrations.retell.schemas import (
    RetellInboundCallPayload,
    RetellInboundCallResponse,
    RetellInboundCallResponseData,
    RetellLifecycleWebhookPayload,
)
from src.modules.voice.policies import UNKNOWN_CALLER_MESSAGE
from src.modules.voice.integrations.retell.security import verify_retell_signature
from src.modules.voice.integrations.retell.websocket_session import RetellWebsocketSession
from src.modules.voice.service import VoiceConversationService
from src.modules.voice.session_store import VoiceSessionStore


class RetellAdapter:
    def __init__(
        self,
        *,
        voice_service: VoiceConversationService,
        session_store: VoiceSessionStore,
        settings: Settings,
    ) -> None:
        self.voice_service = voice_service
        self.session_store = session_store
        self.settings = settings

    async def handle_inbound_http_request(
        self,
        *,
        raw_body: str,
        signature: str | None,
    ) -> RetellInboundCallResponse:
        """Handle the inbound-call webhook Retell sends before a phone call starts.

        This verifies the webhook, checks whether the caller is allowed into the
        voice flow, and returns the Retell response for that decision.

        Notes:
        - This is where we attach `conversation_id` metadata to the Retell call.
        - Unknown callers are rejected with an empty `call_inbound` object.
        """
        if self.settings.retell_verify_signatures and not verify_retell_signature(
            raw_body=raw_body,
            signature=signature,
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Retell signature",
            )

        payload = self._parse_inbound_payload(raw_body)
        inbound_fingerprint = hashlib.sha256(raw_body.encode("utf-8")).hexdigest()
        decision = await self.voice_service.accept_inbound_call(
            caller_phone=payload.call_inbound.from_number,
            provider="retell",
            inbound_fingerprint=inbound_fingerprint,
        )
        if not self.settings.retell_inbound_voice_agent_id:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Retell inbound voice agent id is not configured",
            )

        if not decision.accepted:
            return RetellInboundCallResponse(
                call_inbound=RetellInboundCallResponseData(
                    override_agent_id=self.settings.retell_inbound_voice_agent_id,
                    metadata={
                        "provider": "retell",
                        "special_case": "unknown_caller",
                        "message": UNKNOWN_CALLER_MESSAGE,
                    },
                )
            )

        # Retell expects the inbound-webhook reply to be wrapped under
        # `call_inbound`. We use `override_agent_id` to tell Retell which voice
        # agent should answer this call, and `metadata` to carry our Kira ids into
        # the later websocket and lifecycle webhook events.
        # Docs: https://docs.retellai.com/features/inbound-call-webhook
        return RetellInboundCallResponse(
            call_inbound=RetellInboundCallResponseData(
                override_agent_id=self.settings.retell_inbound_voice_agent_id,
                metadata={
                    "conversation_id": decision.conversation_id,
                    "parent_id": decision.parent_id,
                    "parent_phone": decision.parent_phone,
                    "provider": "retell",
                },
            )
        )

    async def handle_lifecycle_http_request(
        self,
        *,
        raw_body: str,
        signature: str | None,
    ) -> None:
        """Handle lifecycle events like started, ended, and analyzed.

        These events are only for bookkeeping. We verify the webhook, map the call
        back to a Kira conversation, and update the saved status if we can.

        Notes:
        - Missing `conversation_id` metadata is logged and ignored.
        - `call_started` keeps the conversation active; the end/analyzed events decide
          whether it completed or failed.
        """
        if self.settings.retell_verify_signatures and not verify_retell_signature(
            raw_body=raw_body,
            signature=signature,
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Retell signature",
            )

        payload = self._parse_lifecycle_payload(raw_body)
        conversation_id = (payload.call.metadata or {}).get("conversation_id")
        if not conversation_id:
            logger.warning(
                "Retell lifecycle event {} missing conversation_id metadata for call {}",
                payload.event,
                payload.call.call_id,
            )
            return

        if payload.event == "call_started":
            await self.voice_service.conversation_service.update_conversation_status(
                conversation_id,
                new_status=CONVERSATION_STATUS_ACTIVE,
            )
            return

        if payload.event not in {"call_ended", "call_analyzed"}:
            logger.info(
                "Ignoring unsupported Retell lifecycle event {} for call {}",
                payload.event,
                payload.call.call_id,
            )
            return

        failed = self._is_failed_call(
            call_status=payload.call.call_status,
            disconnection_reason=payload.call.disconnection_reason,
        )
        await self.voice_service.complete_call(
            conversation_id=conversation_id,
            failed=failed,
        )

        logger.info(
            "Processed Retell lifecycle event={} conversation={} call_id={} failed={}",
            payload.event,
            conversation_id,
            payload.call.call_id,
            failed,
        )

    async def handle_websocket(
        self,
        *,
        websocket: WebSocket,
        call_id: str,
    ) -> None:
        """Run the live websocket session for one Retell call."""
        session = RetellWebsocketSession(
            websocket=websocket,
            call_id=call_id,
            voice_service=self.voice_service,
            session_store=self.session_store,
            settings=self.settings,
        )
        await session.run()

    def _parse_inbound_payload(self, raw_body: str) -> RetellInboundCallPayload:
        payload = self._parse_json_body(raw_body)
        if payload.get("event") != "call_inbound" or "call_inbound" not in payload:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Expected a Retell inbound-call payload on this endpoint. "
                    "Lifecycle events like call_started/call_ended must be sent to "
                    "/integrations/retell/webhook."
                ),
            )
        return RetellInboundCallPayload.model_validate(payload)

    def _parse_lifecycle_payload(self, raw_body: str) -> RetellLifecycleWebhookPayload:
        payload = self._parse_json_body(raw_body)
        if "call" not in payload:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Expected a Retell lifecycle webhook payload on this endpoint.",
            )

        # Retell lifecycle webhooks come in as `{event, call}` where `event` is
        # something like `call_started` / `call_ended` / `call_analyzed`, and
        # `call` is the normal Retell call object.
        # Docs: https://docs.retellai.com/features/webhook-overview#sample-payload
        return RetellLifecycleWebhookPayload.model_validate(payload)

    def _is_failed_call(
        self,
        *,
        call_status: str | None,
        disconnection_reason: str | None,
    ) -> bool:
        normalized_status = str(call_status or "").lower()
        normalized_reason = str(disconnection_reason or "").lower()
        return normalized_status in {"error", "failed"} or normalized_reason in {
            "error",
            "agent_error",
            "system_error",
        }

    def _parse_json_body(self, raw_body: str) -> dict[str, object]:
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Retell request body must be valid JSON",
            ) from exc

        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Retell request body must be a JSON object",
            )
        return payload

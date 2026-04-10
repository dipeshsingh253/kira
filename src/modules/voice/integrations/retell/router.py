from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, WebSocket, status

from src.modules.voice.integrations.retell.adapter import RetellAdapter
from src.modules.voice.integrations.retell.dependencies import get_retell_adapter
from src.modules.voice.integrations.retell.schemas import RetellInboundCallResponse

router = APIRouter(prefix="/integrations/retell", tags=["retell"])


@router.post(
    "/inbound-call",
    response_model=RetellInboundCallResponse,
    response_model_exclude_none=True,
)
async def handle_inbound_call(
    request: Request,
    adapter: RetellAdapter = Depends(get_retell_adapter),
) -> RetellInboundCallResponse:
    """Handle the webhook Retell sends before it connects an inbound phone call.

    The router only reads the request body and signature header, then hands both to
    the Retell adapter. All provider-specific validation and decision-making lives
    below this layer.
    """
    raw_body = (await request.body()).decode("utf-8")
    return await adapter.handle_inbound_http_request(
        raw_body=raw_body,
        signature=request.headers.get("x-retell-signature"),
    )


@router.options(
    "/inbound-call",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def handle_inbound_call_options() -> Response:
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers={"Allow": "POST, OPTIONS"},
    )


@router.post(
    "/webhook",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def handle_lifecycle_webhook(
    request: Request,
    adapter: RetellAdapter = Depends(get_retell_adapter),
) -> Response:
    """Handle Retell lifecycle events after the call is already underway.

    The router only passes the raw payload and signature header into the adapter.
    The adapter owns provider verification and the call-status update logic.
    """
    raw_body = (await request.body()).decode("utf-8")
    await adapter.handle_lifecycle_http_request(
        raw_body=raw_body,
        signature=request.headers.get("x-retell-signature"),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.options(
    "/webhook",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def handle_lifecycle_webhook_options() -> Response:
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers={"Allow": "POST, OPTIONS"},
    )


@router.websocket("/llm-websocket/{call_id}")
async def llm_websocket(
    websocket: WebSocket,
    call_id: str,
    adapter: RetellAdapter = Depends(get_retell_adapter),
) -> None:
    """Run the live Retell websocket session for one call.

    The router does not branch on Retell protocol events anymore. It only hands the
    accepted websocket off to the adapter, and the adapter creates the live session
    object that owns the full event loop.
    """
    await adapter.handle_websocket(
        websocket=websocket,
        call_id=call_id,
    )

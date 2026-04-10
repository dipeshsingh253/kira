from fastapi import APIRouter, Depends, status

from src.modules.conversations.dependencies import get_conversation_service
from src.modules.conversations.schemas import (
    ConversationDetailResponse,
    ConversationMessageRequest,
    ConversationMessageResponse,
    ConversationStartRequest,
    ConversationStartResponse,
)
from src.modules.conversations.service import ConversationService

router = APIRouter(prefix="/conversations")


@router.post(
    "/start",
    response_model=ConversationStartResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_conversation(
    payload: ConversationStartRequest,
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationStartResponse:
    return await service.start_conversation(payload)


@router.post(
    "/{conversation_id}/messages",
    response_model=ConversationMessageResponse,
)
async def send_message(
    conversation_id: str,
    payload: ConversationMessageRequest,
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationMessageResponse:
    return await service.send_message(conversation_id, payload)


@router.get(
    "/{conversation_id}",
    response_model=ConversationDetailResponse,
)
async def get_conversation(
    conversation_id: str,
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationDetailResponse:
    return await service.get_conversation(conversation_id)

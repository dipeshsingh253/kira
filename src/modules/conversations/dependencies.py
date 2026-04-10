from fastapi import Depends
from src.core.config import get_settings
from src.modules.agent.dependencies import get_agent_runtime
from src.modules.agent.graph import KiraAgentRuntime
from src.modules.conversations.repository import (
    ConversationRepository,
    get_conversation_repository,
)
from src.modules.conversations.service import ConversationService
from src.modules.profiles.repository import ProfileRepository, get_profile_repository


def get_conversation_service(
    conversation_repository: ConversationRepository = Depends(get_conversation_repository),
    profile_repository: ProfileRepository = Depends(get_profile_repository),
    agent_runtime: KiraAgentRuntime = Depends(get_agent_runtime),
) -> ConversationService:
    return ConversationService(
        conversation_repository=conversation_repository,
        profile_repository=profile_repository,
        agent_runtime=agent_runtime,
        settings=get_settings(),
    )

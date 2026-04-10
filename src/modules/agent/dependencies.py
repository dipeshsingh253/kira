from fastapi import Depends

from src.core.config import get_settings
from src.modules.agent.context import AgentRuntimeContext
from src.modules.agent.graph import KiraAgentRuntime
from src.modules.agent.models import AgentModelRegistry, get_model_registry
from src.modules.conversations.repository import (
    ConversationRepository,
    get_conversation_repository,
)
from src.modules.profiles.repository import ProfileRepository, get_profile_repository


def get_agent_runtime(
    conversation_repository: ConversationRepository = Depends(get_conversation_repository),
    profile_repository: ProfileRepository = Depends(get_profile_repository),
    model_registry: AgentModelRegistry = Depends(get_model_registry),
) -> KiraAgentRuntime:
    context = AgentRuntimeContext(
        conversation_repository=conversation_repository,
        profile_repository=profile_repository,
        model_registry=model_registry,
        settings=get_settings(),
    )
    return KiraAgentRuntime(context)

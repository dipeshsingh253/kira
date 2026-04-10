from __future__ import annotations

from dataclasses import dataclass

from src.core.config import Settings
from src.modules.agent.models import AgentFeatureModel, AgentModelRegistry
from src.modules.conversations.repository import ConversationRepository
from src.modules.profiles.repository import ProfileRepository


@dataclass(frozen=True)
class AgentRuntimeContext:
    conversation_repository: ConversationRepository
    profile_repository: ProfileRepository
    model_registry: AgentModelRegistry
    settings: Settings

    def get_model(self, feature_name: str) -> AgentFeatureModel:
        """Return the configured model for a specific runtime feature."""
        return self.model_registry.get_model(feature_name)

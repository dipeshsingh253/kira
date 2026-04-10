from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

from fastapi import HTTPException, status
from loguru import logger

from src.core.config import Settings
from src.core.constants import (
    CONVERSATION_MESSAGE_TYPE_AGENT_ANSWER,
    CONVERSATION_MESSAGE_TYPE_AGENT_CLARIFICATION,
    CONVERSATION_MESSAGE_TYPE_GREETING,
    CONVERSATION_MESSAGE_TYPE_PARENT_QUERY,
    CONVERSATION_STATUS_ACTIVE,
    MESSAGE_ROLE_AGENT,
    MESSAGE_ROLE_USER,
)
from src.modules.agent.graph import KiraAgentRuntime
from src.modules.agent.results import AgentRunResult
from src.modules.conversations.metadata import build_message_metadata
from src.modules.conversations.model import Conversation, ConversationMessage
from src.modules.conversations.repository import ConversationRepository
from src.modules.conversations.schemas import (
    ChildSummary,
    ConversationDebug,
    ConversationDetailResponse,
    ConversationMessageRecord,
    ConversationMessageRequest,
    ConversationMessageResponse,
    ConversationStartRequest,
    ConversationStartResponse,
    HistoryTurnDebug,
)
from src.modules.profiles.repository import ProfileRepository
from src.modules.profiles.schemas import ParentProfile, StudentProfile
from src.core.utils import deep_merge_dicts


@dataclass(frozen=True)
class ConversationBootstrapResult:
    conversation: Conversation
    default_student: StudentProfile | None
    greeting: str | None = None


@dataclass(frozen=True)
class ConversationTurnResult:
    conversation: Conversation
    parent_profile: ParentProfile
    user_message: ConversationMessage
    agent_message: ConversationMessage
    agent_result: AgentRunResult
    resolved_student_summary: ChildSummary | None


class ConversationService:
    def __init__(
        self,
        conversation_repository: ConversationRepository,
        profile_repository: ProfileRepository,
        agent_runtime: KiraAgentRuntime,
        settings: Settings,
    ) -> None:
        self.conversation_repository = conversation_repository
        self.profile_repository = profile_repository
        self.agent_runtime = agent_runtime
        self.settings = settings

    async def start_conversation(
        self,
        payload: ConversationStartRequest,
    ) -> ConversationStartResponse:
        """Start a new conversation and store the opening Kira message.

        We look up the parent, decide whether we can pick a student right away, create
        the conversation row, and write the greeting as the first agent message.

        Notes:
        - If there is only one student, we tailor the greeting to that child right away.
        - The greeting is stored as a normal agent message so the transcript stays simple.
        """
        parent_profile = self.profile_repository.get_parent_profile_by_phone(payload.parent_phone)
        if parent_profile is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No parent profile found for the provided phone number",
            )

        bootstrap = await self.create_conversation_for_parent(
            parent_profile,
            channel=payload.channel,
            persist_greeting=True,
        )
        logger.info(
            "Started conversation {} for parent {}",
            bootstrap.conversation.id,
            parent_profile.parent_id,
        )

        return ConversationStartResponse(
            conversation_id=bootstrap.conversation.id,
            parent_id=parent_profile.parent_id,
            parent_name=parent_profile.parent.name,
            parent_phone=parent_profile.parent.phone,
            children=[self._child_summary(student) for student in parent_profile.students],
            greeting=bootstrap.greeting or "",
        )

    async def send_message(
        self,
        conversation_id: str,
        payload: ConversationMessageRequest,
    ) -> ConversationMessageResponse:
        """Handle one parent turn from write to reply.

        We store the parent message first, fetch the reduced context window for this
        turn, run the agent, update metadata on both rows, refresh the conversation
        summary if needed, and then commit the whole turn.

        Notes:
        - One parent query always becomes two rows: one user row and one agent row.
        - If the agent fails after the user row is flushed, we roll back so we do not
          leave a half-finished turn in the database. We should send alert in such cases.
        """
        turn = await self.process_parent_turn(
            conversation_id,
            message=payload.message,
        )

        return ConversationMessageResponse(
            conversation_id=turn.conversation.id,
            message_id=turn.agent_message.id,
            agent_message=turn.agent_result.response_text,
            created_at=turn.agent_message.created_at,
            resolved_student=turn.resolved_student_summary,
            debug=self._build_debug(
                debug_enabled=payload.debug,
                agent_result=turn.agent_result,
                parent_profile=turn.parent_profile,
            ),
        )

    async def get_conversation(self, conversation_id: str) -> ConversationDetailResponse:
        """Return the full saved conversation for inspection.

        This is the detail view, so it returns the whole transcript from the database,
        not the smaller context slice we send to the agent during answer generation.

        Notes:
        - The top-level `resolved_student` is inferred from the latest resolved message
          instead of being stored separately on the conversation row.
        """
        conversation = await self.conversation_repository.get_conversation(conversation_id)
        if conversation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )

        parent_profile = self.profile_repository.get_parent_profile_by_id(conversation.parent_id)
        if parent_profile is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Parent profile is missing for this conversation",
            )

        messages = await self.conversation_repository.list_messages(conversation.id)
        latest_resolved_student_id = self._get_latest_resolved_student_id(messages)

        return ConversationDetailResponse(
            conversation_id=conversation.id,
            parent_id=conversation.parent_id,
            parent_name=parent_profile.parent.name,
            parent_phone=parent_profile.parent.phone,
            channel=conversation.channel,
            status=conversation.status,
            summary=conversation.summary,
            resolved_student=self._resolve_student_summary(
                parent_profile,
                latest_resolved_student_id,
            ),
            children=[self._child_summary(student) for student in parent_profile.students],
            messages=[
                ConversationMessageRecord(
                    id=message.id,
                    role=message.role,
                    content=message.content,
                    created_at=message.created_at,
                    resolved_student=self._resolve_student_summary(
                        parent_profile,
                        message.resolved_student_id,
                    ),
                    metadata=message.message_metadata,
                )
                for message in messages
            ],
        )

    async def create_conversation_for_parent(
        self,
        parent_profile: ParentProfile,
        *,
        channel: str,
        persist_greeting: bool,
        greeting_text: str | None = None,
        greeting_message_metadata_extra: dict[str, Any] | None = None,
    ) -> ConversationBootstrapResult:
        default_student = parent_profile.students[0] if len(parent_profile.students) == 1 else None
        greeting = greeting_text or self._build_greeting(parent_profile, default_student)

        conversation = await self.conversation_repository.create_conversation(
            parent_id=parent_profile.parent_id,
            parent_phone=parent_profile.parent.phone,
            channel=channel,
            status=CONVERSATION_STATUS_ACTIVE,
        )

        if persist_greeting:
            await self._create_agent_message(
                conversation_id=conversation.id,
                content=greeting,
                resolved_student_id=default_student.student_id if default_student else None,
                message_type=CONVERSATION_MESSAGE_TYPE_GREETING,
                metadata_extra=greeting_message_metadata_extra,
            )

        await self.conversation_repository.commit()

        return ConversationBootstrapResult(
            conversation=conversation,
            default_student=default_student,
            greeting=greeting if persist_greeting else None,
        )

    async def process_parent_turn(
        self,
        conversation_id: str,
        *,
        message: str,
        user_message_metadata_extra: dict[str, Any] | None = None,
        agent_message_metadata_extra: dict[str, Any] | None = None,
    ) -> ConversationTurnResult:
        conversation, parent_profile = await self._get_conversation_with_parent(conversation_id)

        user_message = await self.conversation_repository.create_message(
            conversation_id=conversation.id,
            role=MESSAGE_ROLE_USER,
            content=message,
            message_metadata=self._merge_metadata(
                build_message_metadata(
                    settings=self.settings,
                    message_type=CONVERSATION_MESSAGE_TYPE_PARENT_QUERY,
                ),
                user_message_metadata_extra,
            ),
        )

        conversation_context = await self.conversation_repository.build_conversation_context(
            conversation.id,
            has_summary=conversation.summary is not None,
            initial_threshold_turns=self.settings.conversation_summary_initial_threshold_turns,
            refresh_interval_turns=self.settings.conversation_summary_refresh_interval_turns,
        )

        started_at = perf_counter()
        try:
            agent_result = await self.agent_runtime.invoke(
                conversation=conversation,
                context_messages=conversation_context.context_messages,
                current_message=message,
            )
        except Exception:
            logger.exception(
                "Agent generation failed for conversation {}",
                conversation.id,
            )
            await self.conversation_repository.rollback()
            raise
        generation_duration_ms = round((perf_counter() - started_at) * 1000, 2)

        user_message.resolved_student_id = agent_result.resolved_student_id
        user_message.message_metadata = self._merge_metadata(
            build_message_metadata(
                settings=self.settings,
                message_type=CONVERSATION_MESSAGE_TYPE_PARENT_QUERY,
                student_resolution_method=agent_result.student_resolution_method,
                student_resolution_explanation=agent_result.student_resolution_explanation,
            ),
            user_message_metadata_extra,
        )

        agent_message_type = (
            CONVERSATION_MESSAGE_TYPE_AGENT_ANSWER
            if agent_result.resolved_student_id is not None
            else CONVERSATION_MESSAGE_TYPE_AGENT_CLARIFICATION
        )
        agent_message = await self._create_agent_message(
            conversation_id=conversation.id,
            content=agent_result.response_text,
            resolved_student_id=agent_result.resolved_student_id,
            message_type=agent_message_type,
            metadata_extra=self._merge_metadata(
                {
                    "timing": {
                        "agent_runtime_duration_ms": generation_duration_ms,
                    }
                },
                agent_message_metadata_extra,
            ),
            student_resolution_method=agent_result.student_resolution_method,
            student_resolution_explanation=agent_result.student_resolution_explanation,
            agent_runtime_duration_ms=generation_duration_ms,
            model_provider=agent_result.provider,
            model_name=agent_result.model_name,
            token_usage=agent_result.usage,
            summary_updated=agent_result.summary_updated,
            summary_parent_turn_checkpoint=agent_result.summary_parent_turn_checkpoint,
        )

        if agent_result.summary_updated:
            conversation.summary = agent_result.summary_text

        await self.conversation_repository.commit()

        resolved_student_summary = self._resolve_student_summary(
            parent_profile,
            agent_result.resolved_student_id,
        )

        logger.info(
            "Answered conversation {} with resolution {}",
            conversation.id,
            agent_result.student_resolution_method,
        )

        return ConversationTurnResult(
            conversation=conversation,
            parent_profile=parent_profile,
            user_message=user_message,
            agent_message=agent_message,
            agent_result=agent_result,
            resolved_student_summary=resolved_student_summary,
        )

    async def persist_agent_message(
        self,
        conversation_id: str,
        *,
        content: str,
        resolved_student_id: str | None = None,
        message_type: str = CONVERSATION_MESSAGE_TYPE_AGENT_ANSWER,
        metadata_extra: dict[str, Any] | None = None,
    ) -> ConversationMessage:
        return await self._create_agent_message(
            conversation_id=conversation_id,
            content=content,
            resolved_student_id=resolved_student_id,
            message_type=message_type,
            metadata_extra=metadata_extra,
        )

    async def update_conversation_status(
        self,
        conversation_id: str,
        *,
        new_status: str,
    ) -> None:
        conversation = await self.conversation_repository.update_conversation_status(
            conversation_id,
            new_status,
        )
        if conversation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )
        await self.conversation_repository.commit()

    def _build_greeting(
        self,
        parent_profile: ParentProfile,
        default_student: StudentProfile | None,
    ) -> str:
        """Build the opening message for a new conversation.

        This is the first thing the parent sees, so it sets the tone and, when needed,
        asks them which student they want to talk about.

        Notes:
        - For multi-student parents, we ask them to choose a child first.
        - For single-student parents, we skip that extra step.
        """
        if default_student is not None:
            return (
                f"Hi {parent_profile.parent.name}, I am Kira. "
                f"I can help you understand how {default_student.name} is doing. "
                "What would you like to know?"
            )

        student_names = ", ".join(student.name for student in parent_profile.students)
        return (
            f"Hi {parent_profile.parent.name}, I am Kira. "
            f"I can help you with {student_names}. "
            "Who would you like to talk about first?"
        )

    def _build_debug(
        self,
        debug_enabled: bool,
        agent_result: AgentRunResult,
        parent_profile: ParentProfile,
    ) -> ConversationDebug | None:
        """Build the optional debug block returned by the API.

        This keeps the debug payload useful for testing without dumping raw internal
        traces or anything provider-specific.

        Notes:
        - We show the message window that actually went into the model, not the full
          stored transcript.
        """
        if not debug_enabled:
            return None

        return ConversationDebug(
            student_resolution_method=agent_result.student_resolution_method,
            student_resolution_explanation=agent_result.student_resolution_explanation,
            profile_facts_used=self._build_profile_facts_used(
                parent_profile,
                agent_result.resolved_student_id,
            ),
            history_turns_used=[
                HistoryTurnDebug(
                    role=message.role,
                    content=message.content,
                    resolved_student_id=message.resolved_student_id,
                )
                for message in agent_result.history_turns_used
            ],
            model_provider=agent_result.provider,
            model_name=agent_result.model_name,
            summary_updated=agent_result.summary_updated,
        )

    def _resolve_student_summary(
        self,
        parent_profile: ParentProfile,
        student_id: str | None,
    ) -> ChildSummary | None:
        """Turn a stored student id into the small child payload used by the API.

        This keeps response shaping in the service instead of pushing API concerns
        down into the profile layer.

        Notes:
        - If the student id is missing or no longer exists in fixture data, we return
          `None` instead of blowing up the response.
        """
        if student_id is None:
            return None

        student = parent_profile.get_student(student_id)
        if student is None:
            return None
        return self._child_summary(student)

    async def _get_conversation_with_parent(
        self,
        conversation_id: str,
    ) -> tuple[Conversation, ParentProfile]:
        conversation = await self.conversation_repository.get_conversation(conversation_id)
        if conversation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )

        parent_profile = self.profile_repository.get_parent_profile_by_id(conversation.parent_id)
        if parent_profile is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Parent profile is missing for this conversation",
            )
        return conversation, parent_profile

    async def _create_agent_message(
        self,
        *,
        conversation_id: str,
        content: str,
        resolved_student_id: str | None,
        message_type: str,
        metadata_extra: dict[str, Any] | None = None,
        student_resolution_method: str | None = None,
        student_resolution_explanation: str | None = None,
        agent_runtime_duration_ms: float | int | None = None,
        model_provider: str | None = None,
        model_name: str | None = None,
        token_usage: dict[str, Any] | None = None,
        summary_updated: bool = False,
        summary_parent_turn_checkpoint: int | None = None,
    ) -> ConversationMessage:
        metadata = build_message_metadata(
            settings=self.settings,
            message_type=message_type,
            student_resolution_method=student_resolution_method,
            student_resolution_explanation=student_resolution_explanation,
            agent_runtime_duration_ms=agent_runtime_duration_ms,
            model_provider=model_provider,
            model_name=model_name,
            token_usage=token_usage,
            summary_updated=summary_updated,
            summary_parent_turn_checkpoint=summary_parent_turn_checkpoint,
        )
        return await self.conversation_repository.create_message(
            conversation_id=conversation_id,
            content=content,
            role=MESSAGE_ROLE_AGENT,
            resolved_student_id=resolved_student_id,
            message_metadata=self._merge_metadata(metadata, metadata_extra),
        )

    def _merge_metadata(
        self,
        base_metadata: dict[str, Any],
        metadata_extra: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return deep_merge_dicts(base_metadata, metadata_extra)

    def _child_summary(self, child: StudentProfile) -> ChildSummary:
        """Shrink a full student profile into the response shape we expose."""
        return ChildSummary.from_profile(child)

    def _build_profile_facts_used(
        self,
        parent_profile: ParentProfile,
        student_id: str | None,
    ) -> dict:
        """Build the profile facts block used by the debug payload.

        We derive this in the service from the resolved student id instead of carrying
        full student objects through the runtime result.
        """
        student = parent_profile.get_student(student_id)
        if student is None:
            return {}
        return student.model_dump()

    def _get_latest_resolved_student_id(
        self,
        messages: list[ConversationMessage],
    ) -> str | None:
        """Pick the latest resolved student from saved message history.

        The API still exposes this as the current active student, but we do not store
        a separate active-student field on the conversation. We derive it from the
        most recent message that already has a resolved student id on it.

        Notes:
        - The latest resolved row wins, whether it is the user row or the agent row.
        """
        for message in reversed(messages):
            if message.resolved_student_id:
                return message.resolved_student_id
        return None

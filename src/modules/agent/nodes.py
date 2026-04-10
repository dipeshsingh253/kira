from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage

from src.core.constants import (
    FEATURE_GENERATE_PARENT_QUERY_RESPONSE,
    FEATURE_REFRESH_CONVERSATION_SUMMARY,
)
from src.modules.agent.context import AgentRuntimeContext
from src.modules.agent.prompts import (
    build_answer_messages,
    build_summary_messages,
    conversation_messages_to_langchain_messages,
    extract_text_content,
)
from src.modules.agent.state import AgentGraphState, PersistedConversationMessage


@dataclass
class KiraAgentNodes:
    context: AgentRuntimeContext

    def resolve_student(self, state: AgentGraphState) -> dict:
        """Work out which student the current parent message is about.

        The message might name a child directly, use something like "daughter", or
        fall back to the most recent previously resolved student from earlier turns.
        We resolve that once here and keep the reason so metadata and debug output can
        explain the decision.

        Notes:
        - This node only decides the student for the turn. The clarification node
          builds the actual fallback response when we cannot resolve one.
        """
        previous_resolved_student_id = self._get_latest_resolved_student_id(
            state["context_messages"]
        )

        resolution = self.context.profile_repository.resolve_student(
            parent_profile=state["parent_profile"],
            message=state["current_message"],
            previous_resolved_student_id=previous_resolved_student_id,
        )
        return {
            "student_resolution_method": resolution.method,
            "student_resolution_explanation": resolution.explanation,
            "resolved_student_id": resolution.student.student_id if resolution.student else None,
            "resolved_student": resolution.student,
            "provider": None,
            "model_name": None,
            "usage": None,
        }

    def route_after_resolution(self, state: AgentGraphState) -> str:
        """Pick the next node based on whether we resolved the student."""
        return (
            "generate_answer"
            if state.get("resolved_student") is not None
            else "build_clarification"
        )

    def build_clarification(self, state: AgentGraphState) -> dict:
        """Return a controlled clarification when we do not know the student yet.

        We keep this path deterministic so we do not waste a model call on something
        simple and predictable.
        """
        clarification = self.context.profile_repository.build_clarification_message(
            state["parent_profile"]
        )

        return {"response_text": clarification, "summary_updated": False}

    async def generate_answer(self, state: AgentGraphState) -> dict:
        """Generate the actual parent-facing answer for this turn.

        We build the prompt from the selected student, the saved conversation summary,
        and the reduced message window, then call the model and normalize the result.

        Notes:
        - We use the reduced context from the repository on purpose instead of the full
          transcript so long threads stay manageable.
        """
        model_input_messages = build_answer_messages(
            parent_profile=state["parent_profile"],
            student=state["resolved_student"],
            history_messages=state["context_messages"],
            conversation_summary=state["conversation"].summary,
        )

        feature_model = self.context.get_model(
            FEATURE_GENERATE_PARENT_QUERY_RESPONSE
        )

        ai_message = await feature_model.client.ainvoke(model_input_messages)
        if not isinstance(ai_message, AIMessage):
            ai_message = AIMessage(content=str(ai_message))
        
        response_metadata = ai_message.response_metadata or {}
        response_text = extract_text_content(
            ai_message.content,
            fallback_text=getattr(ai_message, "text", None),
        )

        return {
            "response_text": response_text,
            "provider": feature_model.provider,
            "model_name": response_metadata.get("model_name") or feature_model.model_name,
            "usage": self.normalize_usage(ai_message.usage_metadata),
            "model_input_messages": model_input_messages,
            "summary_updated": False,
        }

    async def refresh_summary(self, state: AgentGraphState) -> dict:
        """Refresh the saved conversation summary if this turn is a summary turn.

        We look at the saved transcript, check the summary cadence with simple turn
        math, and only summarize the small recent window that still sits outside the
        saved summary.

        Notes:
        - We are intentionally using turn math as the source of truth here and
          assuming scheduled summary refreshes succeed.
        - After the first summary, we fetch only the last `2 * unsummarized_turns - 1`
          persisted messages here because the current agent reply has not been saved
          yet and is appended separately in the summary prompt.
        """
        conversation = state["conversation"]
        all_messages = await self.context.conversation_repository.list_messages(
            conversation.id
        )
        total_parent_turns = self._count_parent_turns(all_messages)
        initial_threshold_turns = (
            self.context.settings.conversation_summary_initial_threshold_turns
        )
        refresh_interval_turns = (
            self.context.settings.conversation_summary_refresh_interval_turns
        )

        if not self._is_summary_turn(
            total_parent_turns,
            initial_threshold_turns,
            refresh_interval_turns,
        ):
            return {
                "summary_text": conversation.summary,
                "summary_updated": False,
                "summary_parent_turn_checkpoint": None,
            }

        if conversation.summary is None:
            unsummarized_messages = all_messages
        else:
            unsummarized_parent_turns = self._count_unsummarized_parent_turns(
                total_parent_turns,
                initial_threshold_turns,
                refresh_interval_turns,
            )
            persisted_message_count = max((2 * unsummarized_parent_turns) - 1, 0)
            unsummarized_messages = (
                all_messages[-persisted_message_count:]
                if persisted_message_count > 0
                else []
            )

        summary_messages = build_summary_messages(
            parent_profile=state["parent_profile"],
            unsummarized_messages=[
                PersistedConversationMessage.from_message(message)
                for message in unsummarized_messages
            ],
            response_text=state["response_text"],
            current_summary=conversation.summary,
        )

        feature_model = self.context.get_model(
            FEATURE_REFRESH_CONVERSATION_SUMMARY
        )

        summary_response = await feature_model.client.ainvoke(summary_messages)
        if not isinstance(summary_response, AIMessage):
            summary_response = AIMessage(content=str(summary_response))

        summary_text = extract_text_content(
            summary_response.content,
            fallback_text=getattr(summary_response, "text", None),
        ).strip()

        return {
            "summary_text": summary_text,
            "summary_updated": True,
            "summary_parent_turn_checkpoint": total_parent_turns,
            "model_input_messages": state.get("model_input_messages")
            or conversation_messages_to_langchain_messages(state["context_messages"]),
        }

    def normalize_usage(self, usage: Any) -> dict[str, Any] | None:
        """Turn provider usage data into a plain dict we can store."""
        if usage is None:
            return None
        if isinstance(usage, dict):
            return usage
        return dict(usage)

    def _get_latest_resolved_student_id(
        self,
        messages: list[PersistedConversationMessage],
    ) -> str | None:
        """Pick the latest previously resolved student from the current context window."""
        for message in reversed(messages):
            if message.resolved_student_id:
                return message.resolved_student_id
        return None

    def _count_parent_turns(
        self,
        messages: list[Any],
    ) -> int:
        """Count completed parent turns from saved conversation rows."""
        return sum(1 for message in messages if message.role == "user")

    def _is_summary_turn(
        self,
        total_parent_turns: int,
        initial_threshold_turns: int,
        refresh_interval_turns: int,
    ) -> bool:
        """Check whether this turn lands on the summary cadence."""
        if total_parent_turns < initial_threshold_turns:
            return False
        return (
            total_parent_turns - initial_threshold_turns
        ) % refresh_interval_turns == 0

    def _count_unsummarized_parent_turns(
        self,
        total_parent_turns: int,
        initial_threshold_turns: int,
        refresh_interval_turns: int,
    ) -> int:
        """Count how many parent turns still sit outside the saved summary."""
        if total_parent_turns <= initial_threshold_turns:
            return total_parent_turns

        unsummarized_turns = (
            total_parent_turns - initial_threshold_turns
        ) % refresh_interval_turns
        return unsummarized_turns or refresh_interval_turns

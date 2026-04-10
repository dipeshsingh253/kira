from __future__ import annotations

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from src.modules.agent.context import AgentRuntimeContext
from src.modules.agent.nodes import KiraAgentNodes
from src.modules.agent.prompts import serialize_history_for_debug
from src.modules.agent.results import AgentDebugMessage, AgentRunResult
from src.modules.agent.state import AgentGraphState, PersistedConversationMessage
from src.modules.conversations.model import Conversation


class KiraAgentRuntime:
    def __init__(self, context: AgentRuntimeContext) -> None:
        self.context = context
        self.nodes = KiraAgentNodes(context)
        self.graph = self.build_graph()

    async def invoke(
        self,
        *,
        conversation: Conversation,
        context_messages: list[ConversationMessage],
        current_message: str,
    ) -> AgentRunResult:
        """Run one parent query through the graph and return the final query result.

        The service gives us the conversation row, the already-trimmed answer context,
        and the current parent message. We do the simple setup work here first, then
        pass only the real turn logic through the graph, and finally reshape the state
        into the runtime result used by the API layer.

        Notes:
        - The context was already trimmed by the repository, so the graph should use
          it as-is and not try to trim it again.
        - The summary node fetches its own refresh context instead of having the
          service push that in ahead of time.
        """
        parent_profile = self.context.profile_repository.get_parent_profile_by_id(
            conversation.parent_id
        )
        if parent_profile is None:
            raise RuntimeError(
                f"Parent profile {conversation.parent_id} was not found for conversation {conversation.id}"
            )

        input_state: AgentGraphState = {
            "conversation": conversation,
            "current_message": current_message,
            "parent_profile": parent_profile,
            "context_messages": [
                PersistedConversationMessage.from_message(message)
                for message in context_messages
            ],
        }
        config = RunnableConfig(
            tags=["kira", "agent", conversation.channel],
            metadata={
                "conversation_id": conversation.id,
                "parent_id": conversation.parent_id,
            },
        )
        state = await self.graph.ainvoke(input_state, config=config)
        history_messages = state.get("model_input_messages") or []

        return AgentRunResult(
            response_text=state["response_text"],
            resolved_student_id=state.get("resolved_student_id"),
            student_resolution_method=state["student_resolution_method"],
            student_resolution_explanation=state["student_resolution_explanation"],
            usage=state.get("usage"),
            model_name=state.get("model_name"),
            provider=state.get("provider"),
            summary_text=state.get("summary_text"),
            summary_updated=state.get("summary_updated", False),
            summary_parent_turn_checkpoint=state.get("summary_parent_turn_checkpoint"),
            history_turns_used=[
                AgentDebugMessage.model_validate(item)
                for item in serialize_history_for_debug(history_messages)
            ],
        )

    def build_graph(self):
        """Wire up the fixed graph we run for every turn.

        The flow is: resolve the student for the current question, generate either a
        clarification or an answer, and then optionally refresh the stored summary.

        Notes:
        - The summary step always runs after the response step because it needs the
          final agent reply in order to build the updated summary.
        """
        graph = StateGraph(AgentGraphState)
        graph.add_node("resolve_student", self.nodes.resolve_student)
        graph.add_node("build_clarification", self.nodes.build_clarification)
        graph.add_node("generate_answer", self.nodes.generate_answer)
        graph.add_node("refresh_summary", self.nodes.refresh_summary)
        graph.add_edge(START, "resolve_student")
        graph.add_conditional_edges(
            "resolve_student",
            self.nodes.route_after_resolution,
            {
                "build_clarification": "build_clarification",
                "generate_answer": "generate_answer",
            },
        )
        graph.add_edge("build_clarification", "refresh_summary")
        graph.add_edge("generate_answer", "refresh_summary")
        graph.add_edge("refresh_summary", END)
        return graph.compile()

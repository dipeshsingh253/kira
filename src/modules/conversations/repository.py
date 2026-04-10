from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.constants import (
    CONVERSATION_STATUS_ACTIVE,
    MESSAGE_ROLE_AGENT,
    MESSAGE_ROLE_USER,
)
from src.db.session import get_db
from src.modules.conversations.model import Conversation, ConversationMessage


@dataclass(frozen=True)
class ConversationTurnContext:
    context_messages: list[ConversationMessage]


class ConversationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_conversation(self, conversation_id: str) -> Conversation | None:
        result = await self.db.execute(
            select(Conversation).where(Conversation.id == conversation_id)
        )
        return result.scalar_one_or_none()

    async def update_conversation_status(
        self,
        conversation_id: str,
        status: str,
    ) -> Conversation | None:
        conversation = await self.get_conversation(conversation_id)
        if conversation is None:
            return None
        conversation.status = status
        await self.db.flush()
        return conversation

    async def list_messages(self, conversation_id: str) -> list[ConversationMessage]:
        result = await self.db.execute(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.message_index.asc())
        )
        return list(result.scalars().all())

    async def build_conversation_context(
        self,
        conversation_id: str,
        *,
        has_summary: bool,
        initial_threshold_turns: int,
        refresh_interval_turns: int,
    ) -> ConversationTurnContext:
        """Build the message window for the answer step.

        Before we have a saved summary, or before we reach the first summary turn, the
        agent gets the full transcript. After that, we use turn math to work out the
        last summary turn before the current turn and only send the raw messages that
        came after it. If that reduced slice lost the student context, we add one older
        anchor message so follow-up questions still resolve correctly.

        Notes:
        - This intentionally trusts the summary cadence math and does not look at
          summary metadata as a source of truth.
        - The anchor message is only for answer context. It is not part of the next
          summary refresh window.
        """
        all_messages = await self.list_messages(conversation_id)
        total_parent_turns = self._count_parent_turns(all_messages)
        if not has_summary or total_parent_turns <= initial_threshold_turns:
            return ConversationTurnContext(context_messages=all_messages)

        last_summary_turn = self._last_summary_turn_before_current(
            total_parent_turns,
            initial_threshold_turns,
            refresh_interval_turns,
        )
        if last_summary_turn is None:
            return ConversationTurnContext(context_messages=all_messages)

        recent_unsummarized_messages = self._messages_after_parent_turn(
            all_messages,
            last_summary_turn,
        )
        context_messages = recent_unsummarized_messages

        if recent_unsummarized_messages and not any(
            message.resolved_student_id is not None
            for message in recent_unsummarized_messages
        ):
            # This anchor keeps active-student continuity for follow-up questions, but it
            # is not part of the new unsummarized interval used for the next summary refresh.
            anchor_message = self._find_latest_resolved_student_message_before(
                all_messages,
                recent_unsummarized_messages[0].id,
            )
            if anchor_message is not None:
                context_messages = [anchor_message, *recent_unsummarized_messages]

        return ConversationTurnContext(
            context_messages=context_messages,
        )

    async def create_conversation(
        self,
        *,
        parent_id: str,
        parent_phone: str,
        channel: str,
        status: str = CONVERSATION_STATUS_ACTIVE,
    ) -> Conversation:
        conversation = Conversation(
            parent_id=parent_id,
            parent_phone=parent_phone,
            channel=channel,
            status=status,
        )
        self.db.add(conversation)
        await self.db.flush()
        return conversation

    async def create_message(
        self,
        *,
        conversation_id: str,
        content: str,
        role: str = MESSAGE_ROLE_AGENT,
        resolved_student_id: str | None = None,
        message_metadata: dict[str, Any] | None = None,
    ) -> ConversationMessage:
        next_message_index = await self._next_message_index(conversation_id)

        message = ConversationMessage(
            conversation_id=conversation_id,
            role=role,
            content=content,
            message_index=next_message_index,
            resolved_student_id=resolved_student_id,
            message_metadata=message_metadata,
        )
        self.db.add(message)
        await self.db.flush()
        return message

    async def commit(self) -> None:
        await self.db.commit()

    async def rollback(self) -> None:
        await self.db.rollback()

    async def _next_message_index(self, conversation_id: str) -> int:
        result = await self.db.execute(
            select(func.max(ConversationMessage.message_index)).where(
                ConversationMessage.conversation_id == conversation_id
            )
        )
        current_max = result.scalar_one()
        return (current_max or 0) + 1

    def _count_parent_turns(self, messages: list[ConversationMessage]) -> int:
        return sum(1 for message in messages if message.role == MESSAGE_ROLE_USER)

    def _is_summary_turn(
        self,
        total_parent_turns: int,
        initial_threshold_turns: int,
        refresh_interval_turns: int,
    ) -> bool:
        if total_parent_turns < initial_threshold_turns:
            return False

        return (
            total_parent_turns - initial_threshold_turns
        ) % refresh_interval_turns == 0

    def _last_summary_turn_before_current(
        self,
        total_parent_turns: int,
        initial_threshold_turns: int,
        refresh_interval_turns: int,
    ) -> int | None:
        if total_parent_turns <= initial_threshold_turns:
            return None

        return initial_threshold_turns + (
            (total_parent_turns - initial_threshold_turns - 1)
            // refresh_interval_turns
        ) * refresh_interval_turns

    def _messages_after_parent_turn(
        self,
        messages: list[ConversationMessage],
        parent_turn_number: int,
    ) -> list[ConversationMessage]:
        """Return messages after the given completed parent turn boundary.

        We find the first user message of the next turn and keep everything from there.
        That gives us the raw window that sits outside the last assumed summary turn.

        Notes:
        - This is purely turn-count based and does not inspect summary metadata.
        - If the expected next turn is missing, we fall back to the full list so we do
          not silently drop context.
        """
        next_turn_number = parent_turn_number + 1
        seen_parent_turns = 0

        for index, message in enumerate(messages):
            if message.role != MESSAGE_ROLE_USER:
                continue

            seen_parent_turns += 1
            if seen_parent_turns == next_turn_number:
                return messages[index:]

        return messages

    def _find_latest_resolved_student_message_before(
        self,
        messages: list[ConversationMessage],
        before_message_id: str,
    ) -> ConversationMessage | None:
        """Find the last earlier message that still points to a student.

        We use this as the anchor when the reduced answer window no longer has any
        explicit student reference left in it.

        Notes:
        - We do not care whether that row was from the user or the agent. We only care
          that it still carries the resolved student id.
        """
        latest_message: ConversationMessage | None = None
        for message in messages:
            if message.id == before_message_id:
                break
            if message.resolved_student_id is not None:
                latest_message = message
        return latest_message


def get_conversation_repository(
    db: AsyncSession = Depends(get_db),
) -> ConversationRepository:
    return ConversationRepository(db)

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from src.core.constants import MESSAGE_ROLE_AGENT, MESSAGE_ROLE_SYSTEM, MESSAGE_ROLE_USER
from src.modules.agent.state import PersistedConversationMessage
from src.modules.profiles.schemas import ParentProfile, StudentProfile

AGENT_SYSTEM_PROMPT = (
    "You are Kira, an AI counselor helping parents understand their child's learning journey. "
    "Speak like a calm, real teacher talking to a parent on a phone call.\n\n"

    "Tone:\n"
    "- Natural, calm, and direct\n"
    "- Slightly informal but not chatty\n"
    "- Use simple, everyday language\n"
    "- Speak like a human explaining, not analyzing\n\n"

    "STRICT RULES:\n"
    "- Start directly with the answer\n"
    "- Do NOT use filler phrases like: 'Yeah', 'Yeah, so', 'So', 'Well', 'Right'\n"
    "- Keep responses SHORT (2–4 sentences max)\n"
    "- One idea per sentence\n"
    "- Do NOT sound like a report, dashboard, or analysis\n"
    "- Avoid phrases like: 'signals show', 'is flagged', 'relatively low', 'data suggests'\n"
    "- Do NOT include too many details, numbers, or metrics\n\n"

    "Conversation behavior:\n"
    "- Treat this as a continuous conversation, not separate answers\n"
    "- Check what has already been discussed before answering\n"
    "- If the topic was already covered, do NOT repeat the full explanation\n"
    "- Give a shorter continuation or a refined point instead\n"
    "- Avoid repeating the same strengths, weaknesses, or examples again and again\n\n"

    "Answering style:\n"
    "- First give a clear overall answer\n"
    "- Then 1–2 simple supporting points\n"
    "- Keep it easy to follow in spoken form\n"
    "- Answer only what is asked, do not add extra context\n\n"

    "Suggestions:\n"
    "- Do NOT give suggestions, advice, or next steps in any form\n\n"

    "Capability boundaries:\n"
    "- You cannot perform real-world actions\n"
    "- Do NOT say things like 'I will set up', 'I will send', 'I will schedule'\n\n"

    "Conversation control:\n"
    "- If the question is unclear, ask for clarification briefly\n"
    "- If the question is unrelated to the student, gently say you can only help with the child’s progress\n"
    "- Do NOT reset the conversation or lose context unnecessarily\n\n"

    "Data usage:\n"
    "- Use only the provided student data, summary, and conversation context\n"
    "- Do NOT hallucinate or assume missing information\n\n"

    "Final rule:\n"
    "- If the response feels long or detailed, shorten it before answering\n\n"

    "Goal:\n"
    "- The parent should feel like they spoke to a clear, thoughtful teacher, not an AI"
)

SUMMARY_SYSTEM_PROMPT = (
    "You are maintaining a running conversation summary for an AI counselor.\n\n"

    "Goal:\n"
    "Capture conversation context clearly so future responses feel continuous and non-repetitive.\n\n"

    "Instructions:\n"
    "- Append new information to the existing summary\n"
    "- Preserve important past context (do NOT overwrite blindly)\n"
    "- Only compress when needed to stay within limits\n\n"

    "What to capture:\n"
    "- Parent name (if known)\n"
    "- Conversation history as bullets:\n"
    "  • Parent asked about <student/topic> → answered: <key insight>\n\n"

    "Rules:\n"
    "- Each bullet must clearly mention the student or topic\n"
    "- Keep it concise but meaningful (no vague bullets)\n"
    "- Do NOT drop key insights like strengths, weaknesses, or decisions\n"
    "- Avoid repeating the same information multiple times\n"
    "- Merge similar past bullets instead of duplicating\n\n"

    "Size constraint:\n"
    "- Keep total summary under 500 words\n"
    "- If exceeding, compress older bullets but retain key facts\n\n"

    "Output format:\n"
    "- Bullet points only\n"
    "- No extra explanation\n"
)


def _format_signal_rows(
    rows: list[dict[str, Any]],
    *,
    label_key: str,
    score_key: str,
) -> str:
    formatted_rows = []
    for row in rows:
        label = row.get(label_key)
        score = row.get(score_key)
        if not label:
            continue
        if score is None:
            formatted_rows.append(str(label))
        else:
            formatted_rows.append(f"{label} ({score})")
    return "; ".join(formatted_rows) if formatted_rows else "Not available"


def _format_behavioral_traits(rows: list[dict[str, Any]]) -> str:
    formatted_rows = []
    for row in rows:
        trait = row.get("trait")
        level = row.get("level")
        if not trait:
            continue
        if level:
            formatted_rows.append(f"{trait}: {level}")
        else:
            formatted_rows.append(str(trait))
    return "; ".join(formatted_rows) if formatted_rows else "Not available"


def _format_recent_activity(rows: list[dict[str, Any]]) -> str:
    formatted_rows = []
    for row in rows:
        title = row.get("title")
        activity_type = row.get("type")
        if not title:
            continue
        if activity_type:
            formatted_rows.append(f"{activity_type}: {title}")
        else:
            formatted_rows.append(str(title))
    return "; ".join(formatted_rows) if formatted_rows else "Not available"


def _format_subject_performance(rows: list[dict[str, Any]]) -> str:
    formatted_rows = []
    for row in rows:
        subject = row.get("subject")
        status = row.get("status")
        trend = row.get("trend")
        if not subject:
            continue
        if status and trend:
            formatted_rows.append(f"{subject}: {status} ({trend})")
        elif status:
            formatted_rows.append(f"{subject}: {status}")
        elif trend:
            formatted_rows.append(f"{subject}: {trend}")
    return "; ".join(formatted_rows) if formatted_rows else "Not available"


def serialize_history_for_debug(messages: Iterable[BaseMessage]) -> list[dict]:
    """Turn LangChain messages into the simple debug shape we return in the API.

    We strip out provider-specific structure and keep only the parts that help us see
    what the model actually received.

    Notes:
    - We store plain extracted text here so debug output stays readable.
    """
    serialized_messages: list[dict] = []
    for message in messages:
        role = "system"
        if isinstance(message, HumanMessage):
            role = MESSAGE_ROLE_USER
        elif isinstance(message, AIMessage):
            role = MESSAGE_ROLE_AGENT
        serialized_messages.append(
            {
                "role": role,
                "content": extract_text_content(
                    message.content,
                    fallback_text=getattr(message, "text", None),
                ),
                "resolved_student_id": message.additional_kwargs.get("resolved_student_id"),
            }
        )
    return serialized_messages


def conversation_messages_to_langchain_messages(
    messages: list[PersistedConversationMessage],
) -> list[BaseMessage]:
    """Convert our stored message shape into LangChain message objects.

    We keep the runtime state simple and only convert into framework message classes
    right before prompt building.

    Notes:
    - We keep `resolved_student_id` in `additional_kwargs` so student continuity is
      still visible after conversion.
    """
    langchain_messages: list[BaseMessage] = []
    for message in messages:
        additional_kwargs = {}
        if message.resolved_student_id is not None:
            additional_kwargs["resolved_student_id"] = message.resolved_student_id

        if message.role == MESSAGE_ROLE_USER:
            langchain_messages.append(
                HumanMessage(content=message.content, additional_kwargs=additional_kwargs)
            )
        elif message.role == MESSAGE_ROLE_SYSTEM:
            langchain_messages.append(
                SystemMessage(content=message.content, additional_kwargs=additional_kwargs)
            )
        else:
            langchain_messages.append(
                AIMessage(content=message.content, additional_kwargs=additional_kwargs)
            )
    return langchain_messages


def build_answer_messages(
    *,
    parent_profile: ParentProfile,
    student: StudentProfile,
    history_messages: list[PersistedConversationMessage],
    conversation_summary: str | None,
) -> list[BaseMessage]:
    """Build the prompt for a normal answer turn.

    We combine the base system instruction, the selected student facts, the saved
    summary, and the reduced message window for this turn.

    Notes:
    - Missing facts are written as "Not available" on purpose so the model is pushed
      to stay honest instead of making things up.
    """
    summary_text = conversation_summary or "No conversation summary yet."
    available_students = ", ".join(item.name for item in parent_profile.students)
    extra_facts = student.extra_facts or {}
    basic_profile = extra_facts.get("basic_profile") or {}
    school_performance = extra_facts.get("school_performance") or {}
    platform_activity = extra_facts.get("platform_activity") or {}
    activity_summary = platform_activity.get("summary") or {}
    profile_summary = extra_facts.get("profile_summary") or {}
    grounding_message = SystemMessage(
        content="\n".join(
            [
                f"Parent: {parent_profile.parent.name}",
                f"Available students: {available_students}",
                f"Username: {student.username or 'Not available'}",
                f"Selected student: {student.name} ({student.relation}, class {student.grade})",
                f"School: {student.school}",
                f"Conversation summary: {summary_text}",
                "Previous academic percentage: "
                + str(
                    (basic_profile.get("previous_academic") or {}).get("percentage")
                    or "Not available"
                ),
                "Preferred learning style: "
                + str(basic_profile.get("preferred_learning_style") or "Not available"),
                "Favourite subjects: "
                + (
                    "; ".join(basic_profile.get("favourite_subjects") or [])
                    if basic_profile.get("favourite_subjects")
                    else "Not available"
                ),
                f"Progress: {'; '.join(student.progress) if student.progress else 'Not available'}",
                "Improvement areas: "
                + (
                    "; ".join(student.improvement_areas)
                    if student.improvement_areas
                    else "Not available"
                ),
                f"Interests: {'; '.join(student.interests) if student.interests else 'Not available'}",
                "Career signals: "
                + (
                    "; ".join(student.career_signals)
                    if student.career_signals
                    else "Not available"
                ),
                "School performance overall: "
                + str(school_performance.get("overall") or "Not available"),
                "Subject performance: "
                + _format_subject_performance(school_performance.get("subjects") or []),
                "Platform activity summary: "
                + str(activity_summary or "Not available"),
                "Interest signals: "
                + _format_signal_rows(
                    extra_facts.get("interest_signals") or [],
                    label_key="area",
                    score_key="score",
                ),
                "Skill signals: "
                + _format_signal_rows(
                    extra_facts.get("skill_signals") or [],
                    label_key="skill",
                    score_key="score",
                ),
                "Behavioral traits: "
                + _format_behavioral_traits(extra_facts.get("behavioral_traits") or []),
                "Recent activity: "
                + _format_recent_activity(extra_facts.get("recent_activity") or []),
                "Profile notes: "
                + str(profile_summary.get("notes") or "Not available"),
                f"Extra facts: {student.extra_facts if student.extra_facts else 'Not available'}",
            ]
        )
    )
    return [
        SystemMessage(content=AGENT_SYSTEM_PROMPT),
        grounding_message,
        *conversation_messages_to_langchain_messages(history_messages),
    ]


def build_summary_messages(
    *,
    parent_profile: ParentProfile,
    unsummarized_messages: list[PersistedConversationMessage],
    response_text: str,
    current_summary: str | None,
) -> list[BaseMessage]:
    """Build the prompt for refreshing the saved internal summary.

    We give the model the previous summary, the raw messages that are still outside
    that summary, and the latest agent reply.

    Notes:
    - We append the latest reply here because the summary runs before that reply is
      persisted to the database.
    """
    transcript_lines = []
    for message in unsummarized_messages:
        transcript_lines.append(f"{message.role}: {message.content}")
    transcript_lines.append(f"{MESSAGE_ROLE_AGENT}: {response_text}")

    summary_context = current_summary or "No previous summary."
    return [
        SystemMessage(content=SUMMARY_SYSTEM_PROMPT),
        HumanMessage(
            content="\n".join(
                [
                    f"Parent: {parent_profile.parent.name}",
                    f"Previous summary: {summary_context}",
                    "Recent transcript:",
                    *transcript_lines,
                    "Write an updated internal summary in 3-5 concise sentences.",
                ]
            )
        ),
    ]


def extract_text_content(content: Any, *, fallback_text: str | None = None) -> str:
    """Pull plain text out of provider message content blocks.

    Some providers return a simple string, while others return a list of structured
    blocks. This keeps the rest of the code working with normal text either way.
    """
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                stripped = item.strip()
                if stripped:
                    text_parts.append(stripped)
                continue

            if not isinstance(item, dict):
                continue

            item_type = item.get("type")
            if item_type not in {"text", "output_text"}:
                continue

            text_value = item.get("text")
            if isinstance(text_value, str):
                stripped = text_value.strip()
                if stripped:
                    text_parts.append(stripped)

        if text_parts:
            return "\n\n".join(text_parts)

    if fallback_text:
        stripped = fallback_text.strip()
        if stripped:
            return stripped

    return str(content)

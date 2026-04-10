from __future__ import annotations


PROGRESS_MESSAGES: tuple[str, ...] = (
    "Give me a minute, I'm looking into it.",
)
FOLLOW_UP_PROMPT = "Can I help you with something else?"
FAREWELL_MESSAGE = "Thanks for calling, hope you have a good day."
SILENCE_FAREWELL_MESSAGE = (
    "Seems you are not available, feel free to call anytime. Hope you have a good day."
)
UNKNOWN_CALLER_MESSAGE = "Please call using your registered number. Hope you have a good day."
WEB_CALL_PROBE_MESSAGE = "Hey this is working."
CALL_NOT_READY_MESSAGE = "I am sorry, I could not load this call yet. Please try again."
REPEAT_PROMPT_MESSAGE = "I didn't catch that. Could you say it once more?"
RUNTIME_ERROR_MESSAGE = "I'm sorry, I ran into a problem and need to end this call."

_CLOSE_INTENT_PHRASES: tuple[str, ...] = (
    "no thanks",
    "no thank you",
    "nothing else",
    "that's all",
    "that is all",
    "bye",
    "goodbye",
    "thanks for the help",
    "thank you for the help",
    "i am good",
    "i'm good",
)


def build_progress_message(response_id: int) -> str:
    return PROGRESS_MESSAGES[response_id % len(PROGRESS_MESSAGES)]


def is_close_intent(content: str) -> bool:
    normalized_content = " ".join(content.strip().lower().split())
    if not normalized_content:
        return False
    return any(phrase in normalized_content for phrase in _CLOSE_INTENT_PHRASES)

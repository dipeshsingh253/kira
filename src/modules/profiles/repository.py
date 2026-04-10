from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from src.core.config import get_settings
from src.core.constants import (
    STUDENT_RESOLUTION_METHOD_AMBIGUOUS_NAME_MATCH,
    STUDENT_RESOLUTION_METHOD_AMBIGUOUS_RELATION_MATCH,
    STUDENT_RESOLUTION_METHOD_CLARIFICATION_REQUIRED,
    STUDENT_RESOLUTION_METHOD_EXACT_NAME_MATCH,
    STUDENT_RESOLUTION_METHOD_FAMILY_RELATION_MATCH,
    STUDENT_RESOLUTION_METHOD_PREVIOUS_RESOLVED_STUDENT_CONTEXT,
)
from src.modules.profiles.schemas import ParentProfile, StudentResolution
from src.modules.profiles.utils import (
    normalize_phone_for_lookup,
    normalize_text,
)


class ProfileRepository:
    def __init__(self, fixture_path: Path | str) -> None:
        self.fixture_path = Path(fixture_path)
        self._parent_profiles: list[ParentProfile] | None = None

    def get_parent_profile_by_phone(self, phone: str) -> ParentProfile | None:
        normalized_phone = normalize_phone_for_lookup(phone)
        for parent_profile in self._load_parent_profiles():
            if normalize_phone_for_lookup(parent_profile.parent.phone) == normalized_phone:
                return parent_profile
        return None

    def get_parent_profile_by_id(self, parent_id: str) -> ParentProfile | None:
        for parent_profile in self._load_parent_profiles():
            if parent_profile.parent_id == parent_id:
                return parent_profile
        return None

    def resolve_student(
        self,
        parent_profile: ParentProfile,
        message: str,
        previous_resolved_student_id: str | None,
    ) -> StudentResolution:
        """Figure out which student this parent message is about.

        We try the most explicit signals first and only fall back when the message does
        not name a student clearly. The order is: direct student name, family relation
        like `son` or `daughter`, then the most recent previously resolved student
        from earlier turns. If none of those gives us one clear match, we return a
        clarification result instead of guessing.

        Notes:
        - This method is intentionally conservative. If a match is ambiguous, we ask
          the parent to clarify rather than picking a student ourselves.
        - `previous_resolved_student_id` is only a fallback. A fresh explicit mention
          in the current message always wins over old conversation context.
        - Follow-up lines like "How is he doing in maths?" work only because we reuse
          the most recent previously resolved student when the latest message does not
          name one clearly. We are not doing true pronoun resolution for `he` / `she`.
        - This method only decides which student the turn is about. The graph builds
          the actual clarification response when resolution fails.
        """
        normalized_message = normalize_text(message)

        name_matches = [
            student
            for student in parent_profile.students
            if any(
                re.search(rf"\b{re.escape(candidate.lower())}\b", normalized_message)
                for candidate in student.name_candidates()
            )
        ]
        if len(name_matches) == 1:
            return StudentResolution(
                student=name_matches[0],
                method=STUDENT_RESOLUTION_METHOD_EXACT_NAME_MATCH,
                explanation=(
                    "The message named one student directly, so that student was selected."
                ),
            )
        if len(name_matches) > 1:
            return StudentResolution(
                method=STUDENT_RESOLUTION_METHOD_AMBIGUOUS_NAME_MATCH,
                explanation=(
                    "The message matched more than one student name, so clarification is required."
                ),
            )

        for relation in ("son", "daughter"):
            if re.search(rf"\b{relation}\b", normalized_message):
                relation_matches = [
                    student
                    for student in parent_profile.students
                    if student.relation.lower() == relation
                ]
                if len(relation_matches) == 1:
                    return StudentResolution(
                        student=relation_matches[0],
                        method=STUDENT_RESOLUTION_METHOD_FAMILY_RELATION_MATCH,
                        explanation=(
                            "The message referred to a family relation and it matched one student."
                        ),
                    )
                return StudentResolution(
                    method=STUDENT_RESOLUTION_METHOD_AMBIGUOUS_RELATION_MATCH,
                    explanation=(
                        "The message referred to a family relation that matched multiple students, "
                        "so clarification is required."
                    ),
                )

        previous_resolved_student = parent_profile.get_student(previous_resolved_student_id)
        if previous_resolved_student is not None:
            return StudentResolution(
                student=previous_resolved_student,
                method=STUDENT_RESOLUTION_METHOD_PREVIOUS_RESOLVED_STUDENT_CONTEXT,
                explanation=(
                    "No student was named in the latest message, so the most recent "
                    "previously resolved student from the conversation context was reused."
                ),
            )

        return StudentResolution(
            method=STUDENT_RESOLUTION_METHOD_CLARIFICATION_REQUIRED,
            explanation=(
                "The message did not identify a student clearly enough, so clarification is required."
            ),
        )

    def build_clarification_message(self, parent_profile: ParentProfile) -> str:
        student_names = ", ".join(student.name for student in parent_profile.students)
        return (
            f"I can help you with {student_names}. "
            "Please tell me which student you would like to talk about."
        )

    def _load_parent_profiles(self) -> list[ParentProfile]:
        if self._parent_profiles is not None:
            return self._parent_profiles

        if not self.fixture_path.exists():
            raise FileNotFoundError(f"Profile fixture not found at {self.fixture_path}")

        raw_data = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        parent_rows = raw_data["parents"] if isinstance(raw_data, dict) else raw_data
        self._parent_profiles = [ParentProfile.model_validate(row) for row in parent_rows]
        return self._parent_profiles


@lru_cache
def get_profile_repository() -> ProfileRepository:
    settings = get_settings()
    return ProfileRepository(settings.profile_fixture_path)

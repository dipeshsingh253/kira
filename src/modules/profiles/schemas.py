from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, Field, model_validator


class ParentContact(BaseModel):
    name: str
    phone: str


def _dedupe_strings(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _format_overall_status(overall: dict[str, Any]) -> str | None:
    status = overall.get("status")
    trend = overall.get("trend")
    if not status and not trend:
        return None
    if status and trend:
        return f"Overall school performance is {status} with a {trend} trend."
    if status:
        return f"Overall school performance is {status}."
    return f"Overall school performance trend is {trend}."


def _format_positive_subject_signals(subjects: list[dict[str, Any]]) -> list[str]:
    positive_signals: list[str] = []
    for subject in subjects:
        subject_name = subject.get("subject")
        status = subject.get("status")
        trend = subject.get("trend")
        if not subject_name:
            continue
        if status in {"strong", "good"}:
            positive_signals.append(
                f"{subject_name} performance is {status} with a {trend or 'stable'} trend."
            )
        elif trend == "improving":
            positive_signals.append(f"{subject_name} is showing an improving trend.")
    return positive_signals


class StudentProfile(BaseModel):
    student_id: str
    username: str | None = None
    name: str
    relation: str = "child"
    grade: str
    school: str
    progress: list[str] = Field(default_factory=list)
    improvement_areas: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    career_signals: list[str] = Field(default_factory=list)
    extra_facts: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_fixture_shape(cls, value: Any) -> Any:
        if not isinstance(value, dict) or "basic_profile" not in value:
            return value

        basic_profile = value.get("basic_profile") or {}
        profile_summary = value.get("profile_summary") or {}
        school_performance = value.get("school_performance") or {}
        interest_signals = value.get("interest_signals") or []
        career_signal_rows = value.get("career_signals") or []

        progress = list(profile_summary.get("strengths") or [])
        overall_status = _format_overall_status(school_performance.get("overall") or {})
        if overall_status is not None:
            progress.append(overall_status)
        progress.extend(
            _format_positive_subject_signals(school_performance.get("subjects") or [])
        )

        interests = _dedupe_strings(
            [
                *(basic_profile.get("favourite_subjects") or []),
                *(basic_profile.get("career_interests") or []),
                *[
                    signal.get("area", "")
                    for signal in interest_signals
                    if isinstance(signal, dict)
                ],
            ]
        )
        career_signals = _dedupe_strings(
            [
                signal.get("career", "")
                for signal in career_signal_rows
                if isinstance(signal, dict)
            ]
        )

        return {
            "student_id": value.get("student_id") or value.get("username"),
            "username": value.get("username"),
            "name": basic_profile.get("name") or value.get("name"),
            "relation": value.get("relation", "child"),
            "grade": str(basic_profile.get("grade") or value.get("grade") or ""),
            "school": basic_profile.get("school") or value.get("school") or "",
            "progress": _dedupe_strings(progress),
            "improvement_areas": list(profile_summary.get("improvement_areas") or []),
            "interests": interests,
            "career_signals": career_signals,
            "extra_facts": {
                "basic_profile": basic_profile,
                "school_performance": school_performance,
                "platform_activity": value.get("platform_activity") or {},
                "interest_signals": interest_signals,
                "skill_signals": value.get("skill_signals") or [],
                "behavioral_traits": value.get("behavioral_traits") or [],
                "career_signals": career_signal_rows,
                "recent_activity": value.get("recent_activity") or [],
                "profile_summary": profile_summary,
            },
        }

    def name_candidates(self) -> list[str]:
        candidates = [self.name]
        if self.name:
            candidates.append(self.name.split()[0])
        if self.username:
            candidates.append(self.username)
        return _dedupe_strings(candidates)


class ParentProfile(BaseModel):
    parent_id: str
    parent: ParentContact
    students: list[StudentProfile]

    @model_validator(mode="before")
    @classmethod
    def normalize_fixture_shape(cls, value: Any) -> Any:
        if not isinstance(value, dict) or "parent" in value:
            return value

        return {
            "parent_id": value.get("parent_id"),
            "parent": {
                "name": value.get("name"),
                "phone": value.get("phone"),
            },
            "students": value.get("students", []),
        }

    def get_student(self, student_id: str | None) -> StudentProfile | None:
        if student_id is None:
            return None

        for student in self.students:
            if student.student_id == student_id:
                return student
        return None


class StudentResolution(BaseModel):
    student: StudentProfile | None = None
    method: str
    explanation: str

from __future__ import annotations

from threading import Lock


class VoiceMetrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self._counters = {
            "accepted_calls": 0,
            "rejected_calls": 0,
            "voice_turns": 0,
            "fallback_responses": 0,
            "failed_calls": 0,
        }
        self._generation_count = 0
        self._generation_total_ms = 0.0
        self._generation_max_ms = 0.0

    def increment(self, counter_name: str, value: int = 1) -> None:
        with self._lock:
            self._counters[counter_name] = self._counters.get(counter_name, 0) + value

    def record_generation_latency(self, duration_ms: float) -> None:
        with self._lock:
            self._generation_count += 1
            self._generation_total_ms += duration_ms
            self._generation_max_ms = max(self._generation_max_ms, duration_ms)

    def snapshot(self) -> dict[str, int | float]:
        with self._lock:
            average_ms = (
                self._generation_total_ms / self._generation_count
                if self._generation_count
                else 0.0
            )
            return {
                **self._counters,
                "generation_count": self._generation_count,
                "generation_average_ms": round(average_ms, 2),
                "generation_max_ms": round(self._generation_max_ms, 2),
            }

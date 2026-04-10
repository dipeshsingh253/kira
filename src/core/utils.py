from fastapi import Request
from typing import Optional, Dict, Any
from loguru import logger as _logger

from src.core.schemas import Meta, SuccessResponse, PaginationMeta


def deep_merge_dicts(
    base: Dict[str, Any] | None,
    updates: Dict[str, Any] | None,
) -> Dict[str, Any]:
    result: Dict[str, Any] = dict(base or {})
    for key, value in (updates or {}).items():
        existing = result.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            result[key] = deep_merge_dicts(existing, value)
            continue
        result[key] = value
    return result

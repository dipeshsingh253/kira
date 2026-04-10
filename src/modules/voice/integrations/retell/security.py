from __future__ import annotations

import hashlib
import hmac
import re
import time

from src.core.config import get_settings


SIGNATURE_PATTERN = re.compile(r"v=(\d+),d=(.*)")


def verify_retell_signature(
    *,
    raw_body: str,
    api_key: str | None = None,
    signature: str | None,
    max_age_ms: int | None = None,
) -> bool:
    """Verify Retell's `X-Retell-Signature` header against the raw request body.

    Retell signs webhook requests as `v={timestamp},d={hex_digest}` where the
    digest is `HMAC-SHA256(raw_body + timestamp, api_key)`. We also reject stale
    timestamps so old webhook payloads cannot be replayed.

    Docs: https://docs.retellai.com/features/secure-webhook
    """
    if not signature:
        return False

    if api_key is None or max_age_ms is None:
        settings = get_settings()
        if api_key is None:
            api_key = settings.retell_api_key
        if max_age_ms is None:
            max_age_ms = settings.retell_webhook_max_age_ms

    if not api_key:
        return False

    match = SIGNATURE_PATTERN.fullmatch(signature.strip())
    if match is None:
        return False

    timestamp = match.group(1)
    expected_digest = match.group(2)
    now_ms = int(time.time() * 1000)
    if abs(now_ms - int(timestamp)) > max_age_ms:
        return False

    mac = hmac.new(api_key.encode("utf-8"), digestmod=hashlib.sha256)
    mac.update(f"{raw_body}{timestamp}".encode("utf-8"))
    return hmac.compare_digest(mac.hexdigest(), expected_digest)
    

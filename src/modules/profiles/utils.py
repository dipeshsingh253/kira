from __future__ import annotations

import re


def normalize_phone(phone: str) -> str:
    return re.sub(r"\D", "", phone)

# TODO: This currently supports only india/us style 10 digit numbers. This can break for other countries.
def normalize_phone_for_lookup(phone: str, *, local_number_digits: int = 10) -> str:
    normalized = normalize_phone(phone)
    if len(normalized) <= local_number_digits:
        return normalized
    return normalized[-local_number_digits:]


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())

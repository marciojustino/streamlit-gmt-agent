from __future__ import annotations

import re


_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_CPF = re.compile(r"\b\d{3}[.\s]?\d{3}[.\s]?\d{3}[-\s]?\d{2}\b")
_PHONE = re.compile(r"(?<!\w)(?:\+?55\s?)?\(?\d{2}\)?\s?\d{4,5}[-\s]?\d{4}(?!\w)")
_NUMBER_GROUP = re.compile(r"(?<!\w)(?:\d[ -]?){13,19}(?!\w)")


def redact_personal_data(text: str) -> tuple[str, bool]:
    found = False

    def replace_match(_: re.Match[str]) -> str:
        nonlocal found
        found = True
        return "[DADO REMOVIDO]"

    sanitized = _EMAIL.sub(replace_match, text)
    sanitized = _CPF.sub(replace_match, sanitized)
    sanitized = _PHONE.sub(replace_match, sanitized)

    def replace_number_group(match: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", match.group(0))
        if 13 <= len(digits) <= 19:
            return replace_match(match)
        return match.group(0)

    sanitized = _NUMBER_GROUP.sub(replace_number_group, sanitized)
    return sanitized, found

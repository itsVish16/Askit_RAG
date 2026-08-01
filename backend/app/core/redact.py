"""Lightweight PII redaction for persisted chat history.

Not a Presidio replacement. Covers the common PHI surfaces in biomedical
questions (email, phone, SSN, dates, IP) so the InMemorySaver checkpointer
never stores a verbatim identifier. Matched PII is replaced with a category
tag like [EMAIL] so the LLM still sees *that* an email was mentioned.

Pattern order is load-bearing: DATE before PHONE (an ISO date like
2021-03-04 would else match the phone pattern), IPV4 before PHONE. Each
pattern runs on the previous result. When settings.REDACT_PII is False the
caller skips this (passthrough) so debugging isn't slowed.
"""

import re

# Conservatively scoped: we avoid eating normal biomedical text (no bare
# initials, no short digit runs that could be biomedical IDs).
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("DATE", re.compile(
        r"\b(?:\d{4}-\d{2}-\d{2}"  # 2021-03-04
        r"|\d{1,2}/\d{1,2}/\d{2,4}"  # 3/4/21 or 03/04/2021
        r"|\d{1,2}\s(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s\d{4})\b"
    )),
    ("IPV4", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    # International phone: +country digits, 7+ digits, standard punctuation.
    # Matched LAST so dates/SSNs/IPs already masked don't get re-matched.
    ("PHONE", re.compile(r"\+?\d[\d\s().\-]{8,}\d")),
]


def redact_pii(text: str) -> str:
    """Replace detected PII substrings with category tags ([EMAIL] etc)."""
    if not text:
        return text
    for name, pattern in _PATTERNS:
        text = pattern.sub(f"[{name}]", text)
    return text

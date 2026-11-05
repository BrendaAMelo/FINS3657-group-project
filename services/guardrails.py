# Deterministic checks on text the language model writes.
# The model is never trusted blindly.
from __future__ import annotations

import re

import config

ADVICE_PATTERN = re.compile(
    r"\b(you should (buy|sell|hold)|buy now|sell now|we recommend|"
    r"recommend (buying|selling|holding)|(buy|sell|hold) (more|this|the stock|shares))\b",
    re.IGNORECASE,
)

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")

# Matches citation markers such as [1], [1, 4] and [2,3,7].
_CITATION = re.compile(r"\[\s*\d+(?:\s*,\s*\d+)*\s*\]")


def contains_advice(text: str) -> bool:
    return bool(ADVICE_PATTERN.search(text))


def numbers_in(text: str) -> set[str]:
    return {match.group().replace(",", "") for match in _NUMBER.finditer(text)}


def ungrounded_numbers(explanation: str, allowed_texts: list[str]) -> set[str]:
    # Remove citation references before checking numerical claims.
    # Citation indices are references, not financial figures.
    explanation_without_citations = _CITATION.sub("", explanation)

    allowed: set[str] = set()
    for text in allowed_texts:
        allowed |= numbers_in(text)

    return numbers_in(explanation_without_citations) - allowed


def check_explanation(explanation: str, allowed_texts: list[str]) -> str | None:
    # Return the reason an explanation is unacceptable, or None if it passes.
    if not explanation.strip():
        return "the explanation is empty"

    if len(explanation) > config.EXPLANATION_MAX_CHARS:
        return "the explanation is too long"

    if contains_advice(explanation):
        return "the explanation contains advice"

    unknown = ungrounded_numbers(explanation, allowed_texts)
    if unknown:
        return "numbers not found in the cited news: " + ", ".join(sorted(unknown))

    return None

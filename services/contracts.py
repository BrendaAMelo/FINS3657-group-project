# Shared data types and errors. The UI and the backend both depend on this file.

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

Profile = Literal["conservative", "balanced", "aggressive"]
Severity = Literal["high", "medium", "low"]
ExplanationStatus = Literal["ok", "no_news", "unavailable", "pending"]


class InputError(ValueError):
    """Raised for bad user input. The message is safe to show to the user as-is."""


@dataclass(frozen=True)
class Source:
    title: str
    url: str
    published: date | None = None


@dataclass(frozen=True)
class Explanation:
    text: str
    status: ExplanationStatus
    sources: tuple[Source, ...] = ()
    related_news: tuple[Source, ...] = ()  # Relevant articles, not necessarily evidence of a cause.


@dataclass(frozen=True)
class Alert:
    client_id: int
    ticker: str
    alert_date: date
    severity: Severity
    detector: str  # e.g. "isolation_forest"
    score: float  # higher = more unusual
    summary: str  # factual one-liner: what was unusual
    explanation: str  # news-based explanation, or a "no clear news found" message
    explanation_status: ExplanationStatus
    sources: tuple[Source, ...] = ()
    validated: bool = True  # False when the monitoring configuration lacks independent evaluation
    related_news: tuple[Source, ...] = ()


@dataclass(frozen=True)
class Holding:
    ticker: str
    quantity: float | None = None


@dataclass(frozen=True)
class Client:
    client_id: int
    name: str
    profile: Profile
    sensitivity_override: float | None = None
    holdings: tuple[Holding, ...] = ()

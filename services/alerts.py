# Alert generation. DUMMY VERSION. Keep the signature and return type tho.
from __future__ import annotations

from datetime import date

from services import clients
from services.contracts import Alert, Source

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def get_alerts(client_id: int) -> list[Alert]:
    # Return alerts for a client's holdings, ranked most severe first.

    # Raises InputError if the client doesn't exist.
    client = clients.get_client(client_id)
    severities = ["high", "medium", "low"]
    fake: list[Alert] = []
    for i, holding in enumerate(client.holdings[:3]):
        has_news = i != 2
        fake.append(
            Alert(
                client_id=client_id,
                ticker=holding.ticker,
                alert_date=date.today(),
                severity=severities[i],
                detector="dummy",
                score=round(0.9 - 0.2 * i, 2),
                summary=f"[FAKE] {holding.ticker} moved more than usual compared with its own history.",
                explanation=("[FAKE] Example explanation based on retrieved articles." if has_news else "No clear news found for this move."),
                explanation_status="ok" if has_news else "no_news",
                sources=(Source(title="Example source", url="https://example.com"),) if has_news else (),
            )
        )
    return sorted(fake, key=lambda a: (_SEVERITY_ORDER[a.severity], -a.score))

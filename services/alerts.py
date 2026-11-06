"""Build real alerts for client holdings; explanations never determine detection."""

from __future__ import annotations

from services import clients, detection
from services.contracts import Alert
from services.explanation_jobs import explain

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def get_alerts(client_id: int, *, generate_explanations: bool = False) -> list[Alert]:
    client = clients.get_client(client_id)
    alerts = []
    for holding in client.holdings:
        for flag in detection.get_flags(holding.ticker, client.profile, client.sensitivity_override):
            explanation = explain(flag.ticker, flag.day, flag.summary, generate=generate_explanations)
            alerts.append(
                Alert(
                    client_id=client_id,
                    ticker=flag.ticker,
                    alert_date=flag.day,
                    severity=flag.severity,
                    detector=flag.detector,
                    score=flag.score,
                    summary=flag.summary,
                    explanation=explanation.text,
                    explanation_status=explanation.status,
                    sources=explanation.sources,
                    related_news=explanation.related_news,
                    # The monitoring window, severity heuristic and overrides are
                    # not an independently validated deployment configuration.
                    validated=False,
                )
            )
    return sorted(alerts, key=lambda a: (_SEVERITY_ORDER[a.severity], -a.score, -a.alert_date.toordinal(), a.ticker))

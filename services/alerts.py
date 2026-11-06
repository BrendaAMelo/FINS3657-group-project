# Alert generation. DUMMY VERSION. Keep the signature and return type tho.
from __future__ import annotations

from datetime import date

from services import clients
from services.contracts import Alert, Source

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}



def get_alerts(client_id: int) -> list[Alert]:
    # Return example alerts for the client's holdings.
    # Raises InputError if the client doesn't exist.
    client = clients.get_client(client_id)

    # Historical events from the research spreadsheet.
    # Scores and severities are illustrative, NOT model outputs.
    example_events = [
        {
            "ticker": "KO",
            "alert_date": date(2025, 12, 11),
            "severity": "medium",
            "score": 0.70,
            "summary": (
                "[DEMO] Coca-Cola announced a leadership transition: "
                "Henrique Braun will become CEO on March 31, 2026, "
                "while James Quincey will become Executive Chairman."
            ),
            "explanation": (
                "On December 10, 2025, Coca-Cola announced "
                "its planned CEO succession after market close. "
                "December 11 was the first trading day following "
                "the announcement. This is a potential event "
                "to investigate, not a confirmed price anomaly."
            ),
            "sources": (
                Source(
                    title="SEC - Coca-Cola CEO Succession",
                    url=(
                        "https://www.sec.gov/Archives/edgar/data/"
                        "21344/000155278125000454/e25454_ex99-1.htm"
                    ),
                ),
            ),
        },
        {
            "ticker": "KO",
            "alert_date": date(2025, 12, 10),
            "severity": "low",
            "score": 0.50,
            "summary": (
                "[DEMO] Federal Reserve announces a "
                "25-basis-point interest rate cut."
            ),
            "explanation": (
                "On December 10, 2025, the Federal Reserve "
                "announced a reduction in its target interest "
                "rate range to 3.50%-3.75%. This market-wide "
                "event could affect Coca-Cola and other stocks. "
                "A stock-specific price impact has not been verified."
            ),
            "sources": (
                Source(
                    title="Federal Reserve - FOMC Statement",
                    url=(
                        "https://www.federalreserve.gov/newsevents/"
                        "pressreleases/monetary20251210a.htm"
                    ),
                ),
            ),
        },
        {
            "ticker": "NVDA",
            "alert_date": date(2025, 12, 10),
            "severity": "high",
            "score": 0.90,
            "summary": (
                "[DEMO] Federal Reserve announces a "
                "25-basis-point interest rate cut."
            ),
            "explanation": (
                "On December 10, 2025, the Federal Reserve "
                "reduced its target interest rate range to "
                "3.50%-3.75%. This market-wide announcement "
                "is relevant to NVIDIA as a technology stock. "
                "The actual price response and anomaly status "
                "still need to be evaluated."
            ),
            "sources": (
                Source(
                    title="Federal Reserve - FOMC Statement",
                    url=(
                        "https://www.federalreserve.gov/newsevents/"
                        "pressreleases/monetary20251210a.htm"
                    ),
                ),
            ),
        },
    ]

    alerts: list[Alert] = []

    # Only show events for stocks held by this client.
    held_tickers = {
        holding.ticker.upper()
        for holding in client.holdings
    }

    for event in example_events:
        if event["ticker"] not in held_tickers:
            continue

        alerts.append(
            Alert(
                client_id=client_id,
                ticker=event["ticker"],
                alert_date=event["alert_date"],
                severity=event["severity"],
                detector="demo",
                score=event["score"],
                summary=event["summary"],
                explanation=event["explanation"],
                explanation_status="ok",
                sources=event["sources"],
            )
        )

    return sorted(
        alerts,
        key=lambda a: (
            _SEVERITY_ORDER[a.severity],
            -a.score
        )
    )

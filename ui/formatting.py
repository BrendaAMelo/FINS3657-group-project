# Pure display helpers: no Streamlit calls, so they are easy to test.
from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date

import pandas as pd

import config
from services.contracts import Alert, Source

SEVERITY_ORDER = ("high", "medium", "low")
_SEVERITY_STYLE = {"high": ("High", "red"), "medium": ("Medium", "orange"), "low": ("Low", "gray")}
TIER_ORDER = ("calm", "balanced", "volatile")
TIER_LABELS = {"calm": "Calm / defensive", "balanced": "Balanced", "volatile": "Volatile"}
PROFILE_HELP = {
    "conservative": "Flags smaller-than-usual moves, so expect more alerts.",
    "balanced": "A middle setting between the other two.",
    "aggressive": "Flags only larger unusual moves, so expect fewer alerts.",
}
_MARKDOWN_SPECIALS = re.compile(r"([\\`*_\[\]()#<>~$|])")


def escape_markdown(text: str) -> str:
    # Make untrusted text display literally (also stops $...$ being read as maths).
    return _MARKDOWN_SPECIALS.sub(r"\\\1", text)


def severity_label(severity: str) -> str:
    label, color = _SEVERITY_STYLE.get(severity, (severity.capitalize(), "gray"))
    return f":{color}[**{escape_markdown(label)}**]"


def severity_counts(alerts: Iterable[Alert]) -> dict[str, int]:
    items = list(alerts)
    return {s: sum(a.severity == s for a in items) for s in SEVERITY_ORDER}


def summary_line(n_alerts: int, n_holdings: int) -> str:
    holdings = f"{n_holdings} holding{'s' if n_holdings != 1 else ''}"
    if n_alerts == 0:
        return f"Nothing unusual across {holdings}."
    verb = "needs" if n_alerts == 1 else "need"
    return f"{n_alerts} of {holdings} {verb} attention"


def explanation_kind(status: str) -> str:
    # How to show an explanation: plain text, an info box, or a warning.
    return {"ok": "text", "no_news": "info"}.get(status, "warning")


def format_date(value: date) -> str:
    return value.strftime("%a %d %b %Y")


def _safe_url(url: str) -> str:
    return url.strip().replace(" ", "%20").replace("(", "%28").replace(")", "%29")


def source_markdown(source: Source) -> str:
    title = escape_markdown(source.title.strip()) or "Source"
    if not source.url.startswith(("http://", "https://")):
        return title
    suffix = f" ({format_date(source.published)})" if source.published else ""
    return f"[{title}]({_safe_url(source.url)}){suffix}"


def ticker_option_label(ticker: str) -> str:
    company = config.STOCK_POOL.get(ticker, {}).get("company", "")
    return f"{ticker} · {company}" if company else ticker


def ordered_tickers() -> list[str]:
    return sorted(
        config.STOCK_POOL,
        key=lambda t: (TIER_ORDER.index(config.STOCK_POOL[t]["tier"]), t),
    )


def available_tickers(held: Iterable[str]) -> list[str]:
    held_set = set(held)
    return [t for t in ordered_tickers() if t not in held_set]


def ticker_table() -> pd.DataFrame:
    rows = [
        {
            "Ticker": t,
            "Company": config.STOCK_POOL[t]["company"],
            "Sector": config.STOCK_POOL[t]["sector"],
            "Tier": TIER_LABELS[config.STOCK_POOL[t]["tier"]],
        }
        for t in ordered_tickers()
    ]
    return pd.DataFrame(rows)

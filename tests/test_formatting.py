from datetime import date

import pytest

import config
from services.contracts import Alert, Source
from ui import formatting


def alert(severity="high"):
    return Alert(
        client_id=1,
        ticker="KO",
        alert_date=date(2026, 3, 12),
        severity=severity,
        detector="isolation_forest",
        score=0.9,
        summary="s",
        explanation="e",
        explanation_status="ok",
    )


def test_escape_markdown_makes_text_literal():
    assert formatting.escape_markdown("Revenue $5 and $6") == r"Revenue \$5 and \$6"
    assert formatting.escape_markdown("[click](http://x)") == r"\[click\]\(http://x\)"
    assert formatting.escape_markdown("a_b *c*") == r"a\_b \*c\*"
    assert formatting.escape_markdown("plain text.") == "plain text."
    assert formatting.escape_markdown("") == ""


def test_severity_labels_use_words_not_only_colour():
    assert formatting.severity_label("high") == ":red[**High**]"
    assert formatting.severity_label("medium") == ":orange[**Medium**]"
    assert "Low" in formatting.severity_label("low")
    assert "Odd" in formatting.severity_label("odd")


def test_severity_counts():
    counts = formatting.severity_counts([alert("high"), alert("high"), alert("low")])
    assert counts == {"high": 2, "medium": 0, "low": 1}


@pytest.mark.parametrize(
    ("alerts", "holdings", "expected"),
    [
        (0, 5, "Nothing unusual across 5 holdings."),
        (0, 1, "Nothing unusual across 1 holding."),
        (1, 5, "1 of 5 holdings needs attention"),
        (3, 5, "3 of 5 holdings need attention"),
    ],
)
def test_summary_line(alerts, holdings, expected):
    assert formatting.summary_line(alerts, holdings) == expected


def test_explanation_kinds():
    assert formatting.explanation_kind("ok") == "text"
    assert formatting.explanation_kind("no_news") == "info"
    assert formatting.explanation_kind("unavailable") == "warning"
    assert formatting.explanation_kind("anything else") == "warning"


def test_format_date():
    assert formatting.format_date(date(2026, 3, 12)) == "Thu 12 Mar 2026"


def test_source_links_are_escaped_and_safe():
    link = formatting.source_markdown(Source("A [big] story", "https://example.com/a_(b)", date(2026, 3, 12)))
    assert link == r"[A \[big\] story](https://example.com/a_%28b%29) (Thu 12 Mar 2026)"


def test_non_web_urls_are_not_linked():
    assert formatting.source_markdown(Source("Bad", "javascript:alert(1)")) == "Bad"
    assert formatting.source_markdown(Source("   ", "https://example.com")) == "[Source](https://example.com)"


def test_ticker_helpers_follow_the_pool():
    ordered = formatting.ordered_tickers()
    assert set(ordered) == set(config.STOCK_POOL)
    tiers = [config.STOCK_POOL[t]["tier"] for t in ordered]
    assert tiers == sorted(tiers, key=formatting.TIER_ORDER.index)
    assert "KO" not in formatting.available_tickers(["KO"])
    assert len(formatting.available_tickers([])) == len(config.STOCK_POOL)
    assert formatting.ticker_option_label("KO") == "KO · The Coca-Cola Company"
    assert formatting.ticker_option_label("ZZZ") == "ZZZ"


def test_ticker_table_lists_every_supported_ticker():
    table = formatting.ticker_table()
    assert set(table["Ticker"]) == set(config.SUPPORTED_TICKERS)
    assert list(table.columns) == ["Ticker", "Company", "Sector", "Tier"]


def test_every_profile_has_help_text():
    assert set(formatting.PROFILE_HELP) == set(config.PROFILES)

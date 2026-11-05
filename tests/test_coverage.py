from datetime import date

import pandas as pd
import pytest

from services import coverage
from services.retrieval import Retrieved


@pytest.mark.parametrize(
    ("count", "level"),
    [(0, "none"), (1, "sparse"), (2, "sparse"), (3, "normal"), (9, "normal"), (10, "heavy")],
)
def test_coverage_levels(count, level):
    assert coverage.coverage_level(count) == level


def events_frame():
    return pd.DataFrame(
        {
            "event_id": ["E001", "E002"],
            "ticker": ["KO", "PG"],
            "announcement_date": pd.to_datetime(["2026-03-11", "2026-03-12"]),
            "first_trading_day": pd.to_datetime(["2026-03-12", "2026-03-12"]),
        }
    )


def test_table_uses_the_announcement_day_as_window_start(monkeypatch):
    seen = []

    def fake_retrieve(ticker, day, start=None):
        seen.append((ticker, day, start))
        covered = ticker == "KO"
        return Retrieved(ticker, date(2026, 3, 11), date(2026, 3, 17), (), 4, covered)

    monkeypatch.setattr(coverage, "retrieve", fake_retrieve)
    table = coverage.build_table(events_frame())
    assert seen[0] == ("KO", date(2026, 3, 12), date(2026, 3, 11))
    assert list(table["news_coverage"]) == ["normal", "unknown"]
    assert pd.isna(table.loc[1, "news_article_count"])


def test_quota_warnings_report_thin_and_unknown_events():
    table = pd.DataFrame({"news_coverage": ["normal", "sparse", "unknown"]})
    text = " ".join(coverage.news_quota_warnings(table))
    assert "only 1 events with sparse or no news" in text
    assert "1 events fall outside" in text


def test_no_warnings_when_quotas_are_met():
    table = pd.DataFrame({"news_coverage": ["none", "sparse", "normal"]})
    assert coverage.news_quota_warnings(table) == []

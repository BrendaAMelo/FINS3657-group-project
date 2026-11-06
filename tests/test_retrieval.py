from datetime import date, datetime

import pytest

import config
from data import news
from data.errors import DataUnavailableError
from data.news import Article
from services import retrieval

FLAG = date(2026, 3, 12)  # a Thursday
MIN = retrieval.MIN_RELEVANCE


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch, make_prices):
    monkeypatch.setattr(config, "NEWS_CACHE_DIR", tmp_path / "news")
    monkeypatch.setattr(retrieval, "load_prices", lambda ticker, validate=False: make_prices(n=600))


def art(i, headline, published="2026-03-12T15:00:00+00:00", summary="", related="KO"):
    return Article(
        id=str(i),
        ticker="KO",
        published=datetime.fromisoformat(published),
        headline=headline,
        summary=summary,
        source="Wire",
        url=f"https://example.com/{i}",
        related=related,
    )


def save(articles, end=date(2026, 10, 30)):
    news.save_snapshot("KO", articles, date(2025, 11, 1), end)


def test_window_counts_trading_days(make_prices):
    calendar = make_prices(n=600).index
    assert retrieval.news_window(calendar, FLAG, 1, 3) == (date(2026, 3, 11), date(2026, 3, 17))


def test_weekend_dates_snap_to_the_next_trading_day(make_prices):
    calendar = make_prices(n=600).index
    window = retrieval.news_window(calendar, date(2026, 3, 14), 1, 3)
    assert window == (date(2026, 3, 13), date(2026, 3, 19))


def test_window_is_clipped_at_the_end_of_the_data(make_prices):
    calendar = make_prices(n=600).index
    window = retrieval.news_window(calendar, date(2026, 11, 10), 1, 3)
    assert window == (date(2026, 10, 29), date(2026, 10, 30))


def test_headline_mentions_are_relevant():
    assert retrieval.relevance_score(art(1, "Coca-Cola raises its outlook"), "KO") >= MIN


def test_summary_only_mentions_need_the_ticker_in_related():
    mention = {"headline": "Beverage makers report", "summary": "Coca-Cola led the group."}
    assert retrieval.relevance_score(art(1, related="KO", **mention), "KO") >= MIN
    assert retrieval.relevance_score(art(2, related="AAPL", **mention), "KO") < MIN


def test_roundups_with_many_tickers_are_not_relevant():
    roundup = art(1, "Stocks to watch", summary="Coca-Cola and others.", related="KO,AAPL,MSFT,JPM")
    assert retrieval.relevance_score(roundup, "KO") < MIN


def test_long_ticker_symbols_count_but_short_ones_do_not():
    assert retrieval.relevance_score(art(1, "AAPL gains", related="AAPL"), "AAPL") >= MIN
    assert retrieval.relevance_score(art(2, "KO round of voting", related="KO"), "KO") < MIN
    assert retrieval.relevance_score(art(3, "Visa reports earnings", related="V"), "V") >= MIN


def test_relevant_articles_are_found_and_unrelated_ones_ignored():
    save([art(1, "Coca-Cola raises its outlook"), art(2, "Apple unveils a phone", related="AAPL")])
    found = retrieval.retrieve("KO", FLAG)
    assert [a.id for a in found.articles] == ["1"]
    assert found.covered


def test_window_uses_eastern_time_dates():
    inside = art(1, "Coca-Cola late story", published="2026-03-18T02:00:00+00:00")  # 22:00 ET, 17 Mar
    outside = art(2, "Coca-Cola next story", published="2026-03-18T05:00:00+00:00")  # 01:00 ET, 18 Mar
    save([inside, outside])
    assert [a.id for a in retrieval.retrieve("KO", FLAG).articles] == ["1"]


def test_near_duplicate_headlines_are_counted_once():
    first = art(1, "Coca-Cola raises outlook after strong quarter", published="2026-03-12T15:00:00+00:00")
    copy = art(2, "Coca-Cola raises outlook after strong quarter - Reuters", published="2026-03-12T16:00:00+00:00")
    save([copy, first])
    found = retrieval.retrieve("KO", FLAG)
    assert [a.id for a in found.articles] == ["1"]
    assert found.distinct_relevant == 1


def test_ranking_prefers_headline_mentions_then_closeness():
    far = art(1, "Coca-Cola names new chief", published="2026-03-17T15:00:00+00:00")
    near = art(2, "Coca-Cola unveils new flavour", published="2026-03-12T15:00:00+00:00")
    weak = art(3, "Beverage makers report", summary="Coca-Cola led.", related="KO")
    save([weak, far, near])
    assert [a.id for a in retrieval.retrieve("KO", FLAG).articles] == ["2", "1", "3"]


def test_results_are_capped_but_the_count_is_kept():
    words = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima".split()
    save([art(i, f"Coca-Cola announces {word}") for i, word in enumerate(words, start=1)])
    found = retrieval.retrieve("KO", FLAG)
    assert len(found.articles) == config.NEWS_MAX_ARTICLES
    assert found.distinct_relevant == 12


def test_windows_outside_the_snapshot_are_not_covered():
    save([art(1, "Coca-Cola raises its outlook")], end=date(2026, 3, 1))
    assert not retrieval.retrieve("KO", FLAG).covered


def test_start_override_widens_the_window():
    early = art(1, "Coca-Cola early story", published="2026-03-10T15:00:00+00:00")
    save([early])
    assert retrieval.retrieve("KO", FLAG).articles == ()
    assert len(retrieval.retrieve("KO", FLAG, start=date(2026, 3, 10)).articles) == 1


def test_missing_snapshot_raises():
    with pytest.raises(DataUnavailableError):
        retrieval.retrieve("KO", FLAG)


def test_clipped_followup_window_is_not_complete_coverage():
    save([art(1, "Coca-Cola raises outlook", published="2026-10-30T15:00:00+00:00")])
    assert not retrieval.retrieve("KO", date(2026, 10, 30)).covered

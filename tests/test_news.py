from datetime import date

import pytest
import requests

import config
from data import news
from data.errors import DataUnavailableError


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "NEWS_CACHE_DIR", tmp_path / "news")
    monkeypatch.setattr(news.time, "sleep", lambda _seconds: None)
    monkeypatch.setenv("NEWS_API_KEY", "test-key")


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = [] if payload is None else payload
        self.text = ""

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def install_fake_get(monkeypatch, responses):
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        item = responses[min(len(calls) - 1, len(responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(news.requests, "get", fake_get)
    return calls


def raw(i=1, **overrides):
    item = {
        "id": i,
        "datetime": 1_767_000_000 + i,
        "headline": f"Headline {i}",
        "summary": "A short summary.",
        "source": "Wire",
        "url": f"https://example.com/{i}",
        "related": "KO",
        "category": "company",
    }
    item.update(overrides)
    return item


JAN1, JAN7 = date(2026, 1, 1), date(2026, 1, 7)


def test_articles_are_parsed(monkeypatch):
    install_fake_get(monkeypatch, [FakeResponse(payload=[raw(1)])])
    [article] = news.fetch_company_news("KO", JAN1, JAN7)
    assert (article.id, article.ticker, article.headline) == ("1", "KO", "Headline 1")
    assert article.published.tzinfo is not None
    assert article.url == "https://example.com/1"


def test_long_summaries_are_truncated(monkeypatch):
    install_fake_get(monkeypatch, [FakeResponse(payload=[raw(1, summary="x" * 1000)])])
    [article] = news.fetch_company_news("KO", JAN1, JAN7)
    assert len(article.summary) == config.NEWS_MAX_SUMMARY_CHARS


def test_unusable_items_are_skipped(monkeypatch):
    payload = [
        raw(1, url=""),
        raw(2, datetime="nope"),
        "not a dict",
        raw(3, headline="   "),
        raw(4, datetime=0),
        raw(5),
    ]
    install_fake_get(monkeypatch, [FakeResponse(payload=payload)])
    assert [a.id for a in news.fetch_company_news("KO", JAN1, JAN7)] == ["5"]


def test_key_goes_in_a_header_not_the_url(monkeypatch):
    calls = install_fake_get(monkeypatch, [FakeResponse()])
    news.fetch_company_news("KO", JAN1, JAN7)
    assert calls[0]["headers"] == {"X-Finnhub-Token": "test-key"}
    assert "token" not in calls[0]["params"]
    assert calls[0]["timeout"] == config.NEWS_TIMEOUT_SECONDS


def test_missing_key_fails_before_any_request(monkeypatch):
    monkeypatch.delenv("NEWS_API_KEY")
    calls = install_fake_get(monkeypatch, [FakeResponse()])
    with pytest.raises(DataUnavailableError):
        news.fetch_company_news("KO", JAN1, JAN7)
    assert calls == []


def test_rejected_key_is_not_retried(monkeypatch):
    calls = install_fake_get(monkeypatch, [FakeResponse(status=401)])
    with pytest.raises(DataUnavailableError) as exc:
        news.fetch_company_news("KO", JAN1, JAN7)
    assert "key" in str(exc.value) and len(calls) == 1


def test_rate_limit_is_retried_then_succeeds(monkeypatch):
    calls = install_fake_get(monkeypatch, [FakeResponse(status=429), FakeResponse(payload=[raw(1)])])
    assert len(news.fetch_company_news("KO", JAN1, JAN7)) == 1
    assert len(calls) == 2


@pytest.mark.parametrize("failure", [FakeResponse(status=500), requests.exceptions.ConnectionError("down")])
def test_gives_up_after_the_configured_retries(monkeypatch, failure):
    calls = install_fake_get(monkeypatch, [failure])
    with pytest.raises(DataUnavailableError) as exc:
        news.fetch_company_news("KO", JAN1, JAN7)
    assert "KO" in str(exc.value) and len(calls) == config.NEWS_RETRIES


@pytest.mark.parametrize("payload", [{"error": "x"}, ValueError("bad json")])
def test_unexpected_responses_are_reported(monkeypatch, payload):
    install_fake_get(monkeypatch, [FakeResponse(payload=payload)])
    with pytest.raises(DataUnavailableError):
        news.fetch_company_news("KO", JAN1, JAN7)


def test_other_http_errors_are_reported_without_retrying(monkeypatch):
    calls = install_fake_get(monkeypatch, [FakeResponse(status=400)])
    with pytest.raises(DataUnavailableError):
        news.fetch_company_news("KO", JAN1, JAN7)
    assert len(calls) == 1


def test_ranges_are_fetched_in_weekly_chunks_with_one_extra_day(monkeypatch):
    calls = install_fake_get(monkeypatch, [FakeResponse()])
    news.fetch_range("KO", JAN1, date(2026, 1, 20))
    spans = [(c["params"]["from"], c["params"]["to"]) for c in calls]
    assert spans == [
        ("2026-01-01", "2026-01-08"),
        ("2026-01-08", "2026-01-15"),
        ("2026-01-15", "2026-01-21"),
    ]


def test_a_full_chunk_is_split_and_refetched(monkeypatch):
    big = FakeResponse(payload=[raw(i) for i in range(100, 100 + config.NEWS_SPLIT_THRESHOLD)])
    calls = install_fake_get(monkeypatch, [big, FakeResponse(payload=[raw(1)]), FakeResponse(payload=[raw(2)])])
    articles = news.fetch_range("KO", JAN1, JAN7)
    assert len(calls) == 3
    assert {a.id for a in articles} == {"1", "2"}


def test_duplicates_across_chunks_are_removed(monkeypatch):
    install_fake_get(monkeypatch, [FakeResponse(payload=[raw(1)])])
    assert len(news.fetch_range("KO", JAN1, date(2026, 1, 20))) == 1


def test_snapshot_round_trip_leaves_no_temporary_files(tmp_path):
    articles = [news._parse("KO", raw(1)), news._parse("KO", raw(2))]
    news.save_snapshot("KO", articles, date(2025, 11, 1), date(2026, 10, 30))
    snapshot = news.load_snapshot("KO")
    assert list(snapshot.articles) == articles
    assert (snapshot.start, snapshot.end) == (date(2025, 11, 1), date(2026, 10, 30))
    assert [p.name for p in (tmp_path / "news").iterdir()] == ["KO.json.gz"]
    assert news.snapshot_exists("KO") and not news.snapshot_exists("PG")


def test_missing_and_corrupt_snapshots_give_clear_errors(tmp_path):
    with pytest.raises(DataUnavailableError):
        news.load_snapshot("KO")
    folder = tmp_path / "news"
    folder.mkdir()
    (folder / "KO.json.gz").write_bytes(b"not a gzip file")
    with pytest.raises(DataUnavailableError):
        news.load_snapshot("KO")


@pytest.mark.parametrize("bad", ["../x", "", "ko", None])
def test_unsafe_tickers_are_rejected(bad):
    with pytest.raises(ValueError):
        news.load_snapshot(bad)


def test_rate_limiter_spaces_requests(monkeypatch):
    sleeps = []
    monkeypatch.setattr(news.time, "sleep", sleeps.append)
    monkeypatch.setattr(news.time, "monotonic", lambda: 100.0)
    limiter = news._RateLimiter(60)  # one request per second
    limiter.wait()
    limiter.wait()
    assert sleeps == [1.0]

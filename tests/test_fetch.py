from datetime import date

import pandas as pd
import pytest
import requests

import config
from data import fetch
from data.errors import DataQualityError, DataUnavailableError


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PRICE_CACHE_DIR", tmp_path / "prices")
    monkeypatch.setattr(fetch.time, "sleep", lambda _seconds: None)


@pytest.fixture
def raw_frame(make_prices):
    # What yfinance returns: timezone-aware index and extra columns.
    raw = make_prices(n=600)
    raw.index = raw.index.tz_localize("UTC")
    raw["Dividends"] = 0.0
    return raw


def install_fake_yfinance(monkeypatch, results):
    # Replace yf.Ticker. Each call to history() returns the next result (or raises it).
    calls = []

    class FakeTicker:
        def __init__(self, ticker):
            self.ticker = ticker

        def history(self, **kwargs):
            calls.append((self.ticker, kwargs))
            result = results[min(len(calls) - 1, len(results) - 1)]
            if isinstance(result, Exception):
                raise result
            return result

    monkeypatch.setattr(fetch.yf, "Ticker", FakeTicker)
    return calls


def test_download_cleans_the_data(monkeypatch, raw_frame):
    install_fake_yfinance(monkeypatch, [raw_frame])
    df = fetch.download_prices("KO", config.HISTORY_START, config.PRICE_DATA_END)
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert df.index.tz is None
    assert df.index.is_monotonic_increasing and not df.index.has_duplicates


def test_download_asks_for_adjusted_prices_through_the_end_date(monkeypatch, raw_frame):
    calls = install_fake_yfinance(monkeypatch, [raw_frame])
    fetch.download_prices("KO", date(2022, 1, 1), date(2026, 10, 30))
    _, kwargs = calls[0]
    assert kwargs["auto_adjust"] is True
    assert kwargs["start"] == "2022-01-01"
    assert kwargs["end"] == "2026-10-31"  # yfinance's end date is exclusive


def test_download_retries_then_succeeds(monkeypatch, raw_frame):
    failure = requests.exceptions.ConnectionError("boom")
    calls = install_fake_yfinance(monkeypatch, [failure, failure, raw_frame])
    fetch.download_prices("KO", config.HISTORY_START, config.PRICE_DATA_END)
    assert len(calls) == 3


def test_download_gives_up_after_the_configured_retries(monkeypatch):
    failure = requests.exceptions.ConnectionError("boom")
    calls = install_fake_yfinance(monkeypatch, [failure])
    with pytest.raises(DataUnavailableError) as exc:
        fetch.download_prices("KO", config.HISTORY_START, config.PRICE_DATA_END)
    assert "KO" in str(exc.value)
    assert len(calls) == config.FETCH_RETRIES


def test_empty_result_is_treated_as_unavailable(monkeypatch):
    calls = install_fake_yfinance(monkeypatch, [pd.DataFrame()])
    with pytest.raises(DataUnavailableError):
        fetch.download_prices("KO", config.HISTORY_START, config.PRICE_DATA_END)
    assert len(calls) == config.FETCH_RETRIES


def test_missing_columns_are_reported_without_retrying(monkeypatch, raw_frame):
    calls = install_fake_yfinance(monkeypatch, [raw_frame.drop(columns=["Volume"])])
    with pytest.raises(DataUnavailableError) as exc:
        fetch.download_prices("KO", config.HISTORY_START, config.PRICE_DATA_END)
    assert "Volume" in str(exc.value)
    assert len(calls) == 1


def test_second_load_uses_the_cache(monkeypatch, raw_frame):
    calls = install_fake_yfinance(monkeypatch, [raw_frame])
    first = fetch.load_prices("KO")
    second = fetch.load_prices("KO")
    assert len(calls) == 1
    pd.testing.assert_frame_equal(first, second, check_freq=False)


def test_refresh_forces_a_new_download(monkeypatch, raw_frame):
    calls = install_fake_yfinance(monkeypatch, [raw_frame])
    fetch.load_prices("KO")
    fetch.load_prices("KO", refresh=True)
    assert len(calls) == 2


def test_cache_metadata_records_the_retrieval(monkeypatch, raw_frame):
    install_fake_yfinance(monkeypatch, [raw_frame])
    df = fetch.load_prices("KO")
    info = fetch.cache_info("KO")
    assert info["ticker"] == "KO"
    assert info["rows"] == len(df)
    assert "retrieved_at" in info and "yfinance" in info["source"]


def test_cache_info_is_none_without_a_cache():
    assert fetch.cache_info("KO") is None


@pytest.mark.parametrize("bad", ["../secrets", "KO/../../x", "", "ko", "TOOLONGX", None])
def test_unsafe_or_malformed_tickers_are_rejected(bad):
    with pytest.raises(ValueError):
        fetch.load_prices(bad)


def test_load_validates_by_default(monkeypatch, make_prices):
    short = make_prices(n=100)
    install_fake_yfinance(monkeypatch, [short])
    with pytest.raises(DataQualityError) as exc:
        fetch.load_prices("KO")
    assert "only 100 days" in str(exc.value)
    assert len(fetch.load_prices("KO", validate=False)) == 100


def test_unreadable_cache_file_gives_a_clear_error(tmp_path):
    cache = tmp_path / "prices"
    cache.mkdir()
    (cache / "KO.csv").write_text("not,a,price,file\n1,2,3,4\n", encoding="utf-8")
    with pytest.raises(DataUnavailableError) as exc:
        fetch.load_prices("KO")
    assert "KO" in str(exc.value)

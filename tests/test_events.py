import csv

import pandas as pd
import pytest

import config
from data import events as ev
from data.errors import DataQualityError, DataUnavailableError


def valid_row(**overrides):
    row = {
        "event_id": "E001",
        "ticker": "KO",
        "company": "The Coca-Cola Company",
        "sector": "Consumer staples",
        "tier": "calm",
        "category": "Earnings surprise",
        "event_description": "Quarterly EPS missed consensus",
        "announcement_date": "2026-02-05",
        "announcement_timing": "after_close",
        "first_trading_day": "2026-02-06",
        "split": "",
        "shared_event_id": "",
        "source_type": "primary",
        "primary_source_url": "https://example.com/8-k",
        "secondary_source_url": "https://example.com/news",
        "saved_article_extract": "Short summary",
        "price_reaction_bucket": "",
        "news_coverage": "",
        "news_article_count": "",
        "researcher": "XX",
        "notes": "",
        "is_example": "FALSE",
    }
    row.update(overrides)
    return row


def write_events(tmp_path, rows, delimiter=","):
    path = tmp_path / "events.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ev.REQUIRED_COLUMNS, delimiter=delimiter)
        writer.writeheader()
        writer.writerows(rows)
    return path


def compliant_rows():
    # 16 valid events that satisfy every quota.
    tickers = list(config.STOCK_POOL)[:16]
    days = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2026-01-05", periods=8)]
    days += [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2026-06-01", periods=8)]
    rows = []
    for i, (ticker, day) in enumerate(zip(tickers, days, strict=True)):
        info = config.STOCK_POOL[ticker]
        rows.append(
            valid_row(
                event_id=f"E{i + 1:03d}",
                ticker=ticker,
                company=info["company"],
                sector=info["sector"],
                tier=info["tier"],
                category=config.EVENT_CATEGORIES[i % len(config.EVENT_CATEGORIES)],
                announcement_date=day,
                announcement_timing="intraday",
                first_trading_day=day,
            )
        )
    return rows


def test_valid_file_loads_with_parsed_dates_and_split(tmp_path):
    df = ev.load_events(write_events(tmp_path, [valid_row()]))
    assert len(df) == 1
    assert df.loc[0, "first_trading_day"] == pd.Timestamp("2026-02-06")
    assert df.loc[0, "split"] == "dev"


def test_split_boundary_uses_the_first_trading_day(tmp_path):
    rows = [
        valid_row(
            event_id="E001",
            announcement_date="2026-04-30",
            announcement_timing="after_close",
            first_trading_day="2026-05-01",
        ),
        valid_row(
            event_id="E002",
            announcement_date="2026-04-30",
            announcement_timing="intraday",
            first_trading_day="2026-04-30",
        ),
    ]
    df = ev.load_events(write_events(tmp_path, rows))
    assert dict(zip(df["event_id"], df["split"], strict=True)) == {"E001": "test", "E002": "dev"}


def test_split_written_in_the_file_is_ignored(tmp_path):
    df = ev.load_events(write_events(tmp_path, [valid_row(split="test")]))
    assert df.loc[0, "split"] == "dev"


def test_example_rows_are_ignored_by_default_and_never_block_loading(tmp_path):
    rows = [valid_row(), valid_row(event_id="E000", is_example="TRUE", ticker="NOPE")]
    assert len(ev.load_events(write_events(tmp_path, rows))) == 1


def test_example_rows_can_be_included(tmp_path):
    rows = [valid_row(), valid_row(event_id="E000", is_example="TRUE")]
    assert len(ev.load_events(write_events(tmp_path, rows), include_examples=True)) == 2


def test_header_only_file_gives_an_empty_table(tmp_path):
    assert ev.load_events(write_events(tmp_path, [])).empty


def test_semicolon_separated_files_are_accepted(tmp_path):
    df = ev.load_events(write_events(tmp_path, [valid_row()], delimiter=";"))
    assert len(df) == 1


def test_byte_order_mark_from_excel_is_handled(tmp_path):
    path = write_events(tmp_path, [valid_row()])
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    assert len(ev.load_events(path)) == 1


def test_missing_file_gives_a_clear_error(tmp_path):
    with pytest.raises(DataUnavailableError):
        ev.load_events(tmp_path / "nope.csv")


def test_missing_columns_are_named(tmp_path):
    path = tmp_path / "events.csv"
    path.write_text("event_id,ticker\nE001,KO\n", encoding="utf-8")
    with pytest.raises(DataQualityError) as exc:
        ev.load_events(path)
    assert "category" in str(exc.value)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"ticker": "ZZZZ"}, "ticker"),
        ({"category": "Rumour"}, "category"),
        ({"announcement_timing": "whenever"}, "timing"),
        ({"source_type": "blog"}, "source_type"),
        ({"first_trading_day": "06/02/2026"}, "date"),
        ({"first_trading_day": "2026-02-07"}, "weekend"),
        (
            {
                "announcement_date": "2025-06-02",
                "announcement_timing": "intraday",
                "first_trading_day": "2025-06-02",
            },
            "window",
        ),
        ({"first_trading_day": "2026-02-05"}, "after"),
        ({"tier": "volatile"}, "tier"),
        ({"primary_source_url": ""}, "url"),
        ({"event_description": ""}, "description"),
        ({"event_id": ""}, "event_id"),
    ],
)
def test_bad_rows_are_rejected_with_a_readable_reason(tmp_path, overrides, expected):
    with pytest.raises(DataQualityError) as exc:
        ev.load_events(write_events(tmp_path, [valid_row(**overrides)]))
    assert expected in str(exc.value).lower()


def test_duplicate_event_ids_are_rejected(tmp_path):
    with pytest.raises(DataQualityError) as exc:
        ev.load_events(write_events(tmp_path, [valid_row(), valid_row()]))
    assert "more than once" in str(exc.value)


def test_shared_event_rows_must_share_a_trading_day(tmp_path):
    rows = [
        valid_row(event_id="E001", shared_event_id="MW01"),
        valid_row(
            event_id="E002",
            ticker="PG",
            shared_event_id="MW01",
            announcement_date="2026-02-06",
            first_trading_day="2026-02-09",
        ),
    ]
    with pytest.raises(DataQualityError) as exc:
        ev.load_events(write_events(tmp_path, rows))
    assert "MW01" in str(exc.value)


def test_all_problems_are_reported_together(tmp_path):
    rows = [valid_row(ticker="ZZZZ"), valid_row(event_id="E002", category="Rumour")]
    with pytest.raises(DataQualityError) as exc:
        ev.load_events(write_events(tmp_path, rows))
    message = str(exc.value)
    assert "ZZZZ" in message and "Rumour" in message


def test_market_wide_days_only_include_market_wide_rows(tmp_path):
    rows = [
        valid_row(
            event_id="E001",
            category=config.MARKET_WIDE_CATEGORY,
            shared_event_id="MW01",
            announcement_date="2026-09-16",
            announcement_timing="intraday",
            first_trading_day="2026-09-16",
        ),
        valid_row(event_id="E002"),
    ]
    df = ev.load_events(write_events(tmp_path, rows))
    assert ev.market_wide_days(df) == {pd.Timestamp("2026-09-16")}


def test_a_compliant_list_has_no_quota_warnings(tmp_path):
    df = ev.load_events(write_events(tmp_path, compliant_rows()))
    assert ev.quota_warnings(df) == []


def test_quota_warnings_name_what_is_missing(tmp_path):
    df = ev.load_events(write_events(tmp_path, [valid_row()]))
    text = " ".join(ev.quota_warnings(df))
    assert "only 1 events" in text
    assert "dev events" in text and "test events" in text
    assert "calm-tier" in text and "categories" in text

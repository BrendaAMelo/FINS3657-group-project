import pandas as pd
import pytest

from data.errors import DataQualityError
from data.validate import price_problems, validate_prices


def test_clean_data_has_no_problems(make_prices):
    assert price_problems(make_prices()) == []


def test_short_history_is_reported(make_prices):
    assert any("only 100 days" in p for p in price_problems(make_prices(n=100)))


def test_long_gap_is_reported(make_prices):
    df = make_prices(n=600)
    df = df.drop(df.index[300:320])  # about four weeks missing
    assert any("gap" in p for p in price_problems(df))


def test_missing_values_are_reported(make_prices):
    df = make_prices()
    df.iloc[10, df.columns.get_loc("Close")] = float("nan")
    assert any("missing values" in p for p in price_problems(df))


def test_non_positive_prices_are_reported(make_prices):
    df = make_prices()
    df.iloc[10, df.columns.get_loc("Close")] = -1.0
    assert any("negative" in p for p in price_problems(df))


def test_duplicate_dates_are_reported(make_prices):
    df = make_prices()
    df = pd.concat([df, df.iloc[[5]]])
    assert any("sorted and unique" in p for p in price_problems(df))


def test_reversed_dates_are_reported(make_prices):
    assert any("sorted and unique" in p for p in price_problems(make_prices().iloc[::-1]))


def test_stale_data_is_reported(make_prices):
    assert any("ends on" in p for p in price_problems(make_prices(end="2026-08-01")))


def test_missing_columns_are_reported(make_prices):
    problems = price_problems(make_prices().drop(columns=["Volume"]))
    assert problems == ["missing columns: Volume"]


def test_too_many_zero_volume_days_are_reported(make_prices):
    df = make_prices()
    df.iloc[:60, df.columns.get_loc("Volume")] = 0.0
    assert any("no trading volume" in p for p in price_problems(df))


def test_validate_raises_a_message_starting_with_the_ticker(make_prices):
    with pytest.raises(DataQualityError) as exc:
        validate_prices(make_prices(n=100), "KO")
    assert str(exc.value).startswith("KO:")

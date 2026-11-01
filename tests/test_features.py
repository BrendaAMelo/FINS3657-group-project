import pytest
from pandas.testing import assert_frame_equal

import config
from data.features import FEATURE_COLUMNS, build_features


def test_columns_and_no_missing_values(make_prices):
    feats = build_features(make_prices())
    assert list(feats.columns) == FEATURE_COLUMNS
    assert not feats.isna().any().any()
    assert feats.index.is_monotonic_increasing


def test_values_match_a_hand_calculation(make_prices):
    prices = make_prices(n=100)
    feats = build_features(prices)
    day = feats.index[-1]
    i = prices.index.get_loc(day)
    w = config.FEATURE_WINDOW

    expected_ret = prices["Close"].iloc[i] / prices["Close"].iloc[i - 1] - 1
    assert feats.loc[day, "ret"] == pytest.approx(expected_ret)
    assert feats.loc[day, "abs_ret"] == pytest.approx(abs(expected_ret))

    expected_gap = prices["Open"].iloc[i] / prices["Close"].iloc[i - 1] - 1
    assert feats.loc[day, "gap"] == pytest.approx(expected_gap)

    prior_volume = prices["Volume"].iloc[i - w : i].mean()
    assert feats.loc[day, "vol_ratio"] == pytest.approx(prices["Volume"].iloc[i] / prior_volume)

    prior_returns = prices["Close"].pct_change().iloc[i - w : i]
    assert feats.loc[day, "vol_prior"] == pytest.approx(prior_returns.std())


def test_features_do_not_change_when_later_data_is_added(make_prices):
    prices = make_prices(n=300)
    cutoff = prices.index[200]
    full = build_features(prices).loc[:cutoff]
    truncated = build_features(prices.loc[:cutoff])
    assert_frame_equal(full, truncated, check_freq=False)


def test_changing_the_future_does_not_change_the_past(make_prices):
    prices = make_prices(n=300)
    cutoff = prices.index[200]
    altered = prices.copy()
    altered.loc[altered.index > cutoff, ["Open", "Close", "Volume"]] *= 5
    before = build_features(prices).loc[:cutoff]
    after = build_features(altered).loc[:cutoff]
    assert_frame_equal(before, after, check_freq=False)


def test_a_volume_spike_shows_up_on_its_own_day(make_prices):
    prices = make_prices(n=300)
    day = prices.index[250]
    prices.loc[day, "Volume"] *= 10
    assert build_features(prices).loc[day, "vol_ratio"] > 5


def test_a_price_shock_shows_up_in_return_and_gap(make_prices):
    prices = make_prices(n=300)
    day = prices.index[250]
    prices.loc[day, ["Open", "Close"]] *= 0.9
    row = build_features(prices).loc[day]
    assert row["ret"] < -0.05
    assert row["gap"] < -0.05


def test_zero_volume_windows_do_not_create_infinities(make_prices):
    prices = make_prices(n=300)
    prices.iloc[100:130, prices.columns.get_loc("Volume")] = 0.0
    feats = build_features(prices)
    assert not feats.isin([float("inf"), float("-inf")]).any().any()
    assert not feats.isna().any().any()


def test_too_little_data_returns_an_empty_frame(make_prices):
    feats = build_features(make_prices(n=10))
    assert feats.empty
    assert list(feats.columns) == FEATURE_COLUMNS

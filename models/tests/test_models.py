from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from models.detectors import fixed_threshold, isolation_forest, rolling_zscore, run_models


def prices_from_returns(returns):
    close = 100 * np.cumprod(1 + np.array([0, *returns], dtype=float))
    return pd.DataFrame(
        {"Open": close, "Close": close, "Volume": 1000.0},
        index=pd.bdate_range("2024-01-01", periods=len(close), name="Date"),
    )


def random_prices(n=500):
    return prices_from_returns(np.random.default_rng(7).normal(0, 0.01, n))


def test_fixed_up_and_down_and_missing_first_day():
    result = fixed_threshold(prices_from_returns([0.06, -0.06, 0.01]))
    assert result.is_anomaly.tolist() == [False, True, True, False]
    assert result.is_scored.tolist() == [False, True, True, True]


def test_fixed_boundary_is_strict():
    prices = prices_from_returns([0.125, -0.125])
    assert not fixed_threshold(prices, threshold=0.125).is_anomaly.any()
    assert not fixed_threshold(prices_from_returns([0.05, -0.05])).is_anomaly.any()


def test_zscore_excludes_current_return_and_includes_threshold():
    prices = prices_from_returns([0.01, -0.01, 0.02, -0.02, 0.20])
    result = rolling_zscore(prices, window=4)
    returns = prices.Close.pct_change(fill_method=None)
    expected = abs((returns.iloc[-1] - returns.iloc[1:5].mean()) / returns.iloc[1:5].std())
    assert result.score.iloc[-1] == pytest.approx(expected)
    assert not result.is_scored.iloc[:5].any()
    assert rolling_zscore(prices, window=4, threshold=expected).is_anomaly.iloc[-1]


def test_zscore_zero_variance():
    result = rolling_zscore(prices_from_returns([0, 0, 0, 0, 0.1]), window=3)
    assert result.score.iloc[-2] == 0
    assert result.score.iloc[-1] == np.inf
    assert result.is_anomaly.iloc[-1]


@pytest.mark.parametrize("model", [fixed_threshold, rolling_zscore])
def test_future_changes_do_not_change_previous_scores(model):
    prices = random_prices()
    changed = prices.copy()
    changed.loc[changed.index[-20:], ["Open", "Close"]] *= 3
    pd.testing.assert_frame_equal(model(prices).iloc[:-20], model(changed).iloc[:-20])


def test_forest_is_chronological_reproducible_and_profiles_are_nested():
    prices = random_prices()
    cutoff = prices.index[350]
    outputs, metadata = isolation_forest(prices, train_before=cutoff)
    assert pd.Timestamp(metadata["fit_end"]) < pd.Timestamp(metadata["calibration_start"]) < cutoff
    assert pd.Timestamp(metadata["calibration_end"]) < cutoff
    assert not outputs["balanced"].is_scored.loc[: cutoff - pd.Timedelta(days=1)].any()
    thresholds = metadata["thresholds"]
    assert thresholds["conservative"] <= thresholds["balanced"] <= thresholds["aggressive"]
    assert (outputs["aggressive"].is_anomaly <= outputs["balanced"].is_anomaly).all()
    assert (outputs["balanced"].is_anomaly <= outputs["conservative"].is_anomaly).all()
    changed = prices.copy()
    changed.iloc[-10:, changed.columns.get_indexer(["Open", "Close"])] *= 4
    other, other_metadata = isolation_forest(changed, train_before=cutoff)
    assert metadata == other_metadata
    pd.testing.assert_frame_equal(outputs["balanced"].iloc[:-10], other["balanced"].iloc[:-10])


def test_forest_rejects_short_history():
    prices = random_prices(80)
    with pytest.raises(ValueError, match="150"):
        isolation_forest(prices, train_before=prices.index[-1])


@pytest.mark.parametrize("threshold", [0, -1, np.nan, np.inf])
def test_invalid_thresholds(threshold):
    with pytest.raises(ValueError):
        fixed_threshold(random_prices(), threshold)


def test_unsorted_prices_are_rejected():
    with pytest.raises(ValueError, match="sorted"):
        fixed_threshold(random_prices().iloc[::-1])


def test_output_contract_and_profile_independent_baseline():
    prices = random_prices()
    result, _ = run_models(prices, "KO", start=prices.index[350], end=prices.index[-1])
    assert set(result.model) == {"fixed_threshold", "rolling_zscore", "isolation_forest"}
    assert len(result) == 151 * 9
    assert not result.duplicated(["date", "ticker", "model", "profile"]).any()
    fixed = result.loc[result.model == "fixed_threshold"]
    assert fixed.groupby("date").score.nunique().eq(1).all()


def test_insufficient_forest_history_is_reported_without_blocking_baselines():
    prices = random_prices(100)
    result, metadata = run_models(
        prices, "KO", start=prices.index[70], end=prices.index[-1], allow_insufficient_history=True
    )
    assert metadata["status"] == "insufficient_history"
    assert not result.loc[result.model == "isolation_forest", "is_scored"].any()
    assert result.loc[result.model == "fixed_threshold", "is_scored"].all()
    assert result.close_price.notna().all()

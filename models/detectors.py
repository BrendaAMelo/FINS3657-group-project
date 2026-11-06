"""End-of-day detectors. Thresholds and training never use future observations."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

import config
from data.features import FEATURE_COLUMNS, build_features


def _validate(prices: pd.DataFrame) -> None:
    if not isinstance(prices.index, pd.DatetimeIndex) or prices.index.tz is not None:
        raise ValueError("Prices need a timezone-naive DatetimeIndex.")
    if prices.empty or not prices.index.is_monotonic_increasing or prices.index.has_duplicates:
        raise ValueError("Prices must have nonempty, sorted, unique dates.")
    if (prices.index != prices.index.normalize()).any():
        raise ValueError("Prices must use daily dates without time components.")
    for col in ("Open", "Close", "Volume"):
        if col not in prices or not np.isfinite(prices[col]).all():
            raise ValueError(f"Prices need finite {col} values.")
    if (prices[["Open", "Close"]] <= 0).any().any() or (prices["Volume"] < 0).any():
        raise ValueError("Prices must be positive and volume nonnegative.")


def _result(score: pd.Series, threshold: float, *, strict: bool = False) -> pd.DataFrame:
    ready = score.notna()
    flagged = score.gt(threshold) if strict else score.ge(threshold)
    if strict:
        # Division can represent an exact 5% move as 0.050000000000000044.
        flagged &= ~np.isclose(score, threshold, rtol=0, atol=1e-12)
    return pd.DataFrame({"score": score, "threshold": threshold, "is_anomaly": ready & flagged, "is_scored": ready})


def fixed_threshold(prices: pd.DataFrame, threshold: float = config.FIXED_THRESHOLD_PCT) -> pd.DataFrame:
    """Flag absolute close-to-close return strictly above the threshold (0.05 = 5%)."""
    _validate(prices)
    if not np.isfinite(threshold) or threshold <= 0:
        raise ValueError("Fixed threshold must be finite and positive.")
    return _result(prices.Close.pct_change(fill_method=None).abs(), threshold, strict=True)


def rolling_zscore(
    prices: pd.DataFrame,
    window: int = config.ZSCORE_WINDOW,
    threshold: float = 3.0,
) -> pd.DataFrame:
    """Absolute z-score against the previous window of returns, excluding today."""
    _validate(prices)
    if not isinstance(window, int) or window < 2:
        raise ValueError("Z-score window must be an integer of at least two days.")
    if not np.isfinite(threshold) or threshold <= 0:
        raise ValueError("Z-score threshold must be finite and positive.")
    returns = prices.Close.pct_change(fill_method=None)
    prior = returns.shift(1).rolling(window, min_periods=window)
    deviation = (returns - prior.mean()).abs()
    std = prior.std(ddof=1)
    score = deviation / std
    # A flat history followed by a move is infinitely unusual; flat followed by flat is zero.
    score = score.mask((std == 0) & (deviation == 0), 0.0)
    return _result(score, threshold)


def isolation_forest(
    prices: pd.DataFrame,
    *,
    train_before: str | pd.Timestamp,
    profiles: tuple[str, ...] = tuple(config.PROFILES),
    random_state: int = 42,
    allow_insufficient_history: bool = False,
    quantile_override: float | None = None,
) -> tuple[dict[str, pd.DataFrame], dict]:
    """Fit per ticker on early history; calibrate quantiles on later pre-evaluation history."""
    _validate(prices)
    if not profiles or any(p not in config.PROFILES for p in profiles):
        raise ValueError("Choose one or more configured risk profiles.")
    features = build_features(prices)[FEATURE_COLUMNS]
    cutoff = pd.Timestamp(train_before)
    history = features.loc[features.index < cutoff]
    n_fit = int(len(history) * 0.8)
    fit, calibration = history.iloc[:n_fit], history.iloc[n_fit:]
    if len(fit) < 100 or len(calibration) < 30:
        if allow_insufficient_history:
            empty = pd.Series(np.nan, index=prices.index, dtype=float)
            return {p: _result(empty, np.nan) for p in profiles}, {
                "status": "insufficient_history",
                "fit_rows": len(fit),
                "calibration_rows": len(calibration),
            }
        raise ValueError("Isolation Forest needs at least 150 usable feature days before evaluation.")
    forest = IsolationForest(
        n_estimators=200, max_samples="auto", contamination="auto", random_state=random_state, n_jobs=1
    )
    forest.fit(fit)
    calibration_scores = -forest.score_samples(calibration)
    future = features.loc[features.index >= cutoff]
    scores = pd.Series(np.nan, index=prices.index, dtype=float)
    if not future.empty:
        scores.loc[future.index] = -forest.score_samples(future)
    outputs, thresholds = {}, {}
    for profile in profiles:
        quantile = config.PROFILES[profile]["iforest_quantile"] if quantile_override is None else quantile_override
        if not 0 < quantile < 1:
            raise ValueError("Isolation Forest quantiles must be between zero and one.")
        threshold = float(np.quantile(calibration_scores, quantile))
        thresholds[profile] = threshold
        outputs[profile] = _result(scores, threshold)
    return outputs, {
        "fit_start": str(fit.index.min().date()),
        "fit_end": str(fit.index.max().date()),
        "fit_rows": len(fit),
        "calibration_start": str(calibration.index.min().date()),
        "calibration_end": str(calibration.index.max().date()),
        "calibration_rows": len(calibration),
        "thresholds": thresholds,
        "random_state": random_state,
        "n_estimators": 200,
        "feature_columns": FEATURE_COLUMNS,
    }


def run_models(
    prices: pd.DataFrame,
    ticker: str,
    *,
    start=config.EVENT_WINDOW_START,
    end=config.PRICE_DATA_END,
    profiles: tuple[str, ...] = tuple(config.PROFILES),
    allow_insufficient_history: bool = False,
) -> tuple[pd.DataFrame, dict]:
    """One row per trading date, model and profile, including unscored rows."""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    if start > end:
        raise ValueError("Start must be on or before end.")
    forests, metadata = isolation_forest(
        prices, train_before=start, profiles=profiles, allow_insufficient_history=allow_insufficient_history
    )
    fixed = fixed_threshold(prices)
    rows = []
    for profile in profiles:
        detectors = {
            "fixed_threshold": fixed,
            "rolling_zscore": rolling_zscore(prices, threshold=config.PROFILES[profile]["z_threshold"]),
            "isolation_forest": forests[profile],
        }
        for name, frame in detectors.items():
            frame = frame.loc[(frame.index >= start) & (frame.index <= end)].copy()
            frame.index.name = "date"
            frame["ticker"], frame["model"], frame["profile"] = ticker, name, profile
            frame["daily_return"] = prices.Close.pct_change(fill_method=None).reindex(frame.index)
            frame["close_price"] = prices.Close.reindex(frame.index)
            rows.append(frame.reset_index())
    columns = [
        "date",
        "ticker",
        "model",
        "profile",
        "close_price",
        "daily_return",
        "score",
        "threshold",
        "is_anomaly",
        "is_scored",
    ]
    return pd.concat(rows, ignore_index=True)[columns], metadata

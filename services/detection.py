"""Shared real detection for dashboard cards, chart markers and explanation prefetch."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

import numpy as np
import pandas as pd

import config
from data.errors import DataError, DataQualityError
from models.detectors import isolation_forest
from models.history import history_start, load_history
from services.contracts import InputError, Severity


@dataclass(frozen=True)
class Flag:
    ticker: str
    day: date
    detector: str
    score: float
    severity: Severity
    summary: str


def forest_quantile(profile: str, override: float | None) -> float:
    """Map absolute UI sensitivity to forest quantiles; this mapping is experimental."""
    if profile not in config.PROFILES:
        raise InputError("Choose a configured risk profile.")
    if override is None:
        return config.PROFILES[profile]["iforest_quantile"]
    if not np.isfinite(override) or not config.OVERRIDE_MIN <= override <= config.OVERRIDE_MAX:
        raise InputError("Sensitivity is outside the supported range.")
    anchors = {config.OVERRIDE_MIN: 0.95, config.OVERRIDE_MAX: 0.995}
    anchors.update({p["z_threshold"]: p["iforest_quantile"] for p in config.PROFILES.values()})
    points = sorted(anchors.items())
    return float(np.interp(override, [x for x, _ in points], [y for _, y in points]))


def _history_fingerprint(ticker: str) -> tuple:
    interval = f"{history_start(config.MODEL_HISTORY_AS_OF)}_{config.MODEL_HISTORY_AS_OF}"
    folder = config.DATA_DIR / "cache" / "model_prices" / interval
    paths = [folder / f"{ticker}.csv", folder / f"{ticker}.json"]
    return tuple((str(p), p.stat().st_mtime_ns if p.exists() else None) for p in paths)


@lru_cache(maxsize=128)
def _detect(ticker: str, quantile: float, fingerprint: tuple, settings: tuple) -> tuple[pd.DataFrame, tuple[Flag, ...]]:
    del fingerprint  # Cache invalidation only; the loader validates the files themselves.
    as_of, start, end = settings
    try:
        prices, _ = load_history(ticker, as_of)
        # Later observations are excluded even if the ten-year pool extends further.
        prices = prices.loc[prices.index <= pd.Timestamp(end)].copy()
        results, metadata = isolation_forest(
            prices,
            train_before=start,
            profiles=("balanced",),
            quantile_override=quantile,
            allow_insufficient_history=True,
        )
    except (OSError, ValueError) as err:
        raise DataQualityError(f"Could not prepare detection for {ticker}: {err}") from err
    if metadata.get("status") == "insufficient_history":
        raise DataQualityError(f"{ticker}: insufficient pre-monitoring history for Isolation Forest.")
    frame = results["balanced"]
    frame = frame.loc[(frame.index >= pd.Timestamp(start)) & (frame.index <= pd.Timestamp(end))]
    flagged = frame.loc[frame.is_scored & frame.is_anomaly]
    returns = prices.Close.pct_change(fill_method=None)
    flags = []
    for day, row in flagged.iterrows():
        # Severity is a display heuristic, not an estimate of financial loss.
        ratio = float(row.score / row.threshold)
        severity: Severity = "high" if ratio >= 1.2 else ("medium" if ratio >= 1.1 else "low")
        summary = (
            f"{ticker} closed {float(returns.loc[day]):+.2%} versus the previous trading day. "
            "Isolation Forest flagged unusual price/volume features relative to its historical baseline."
        )
        flags.append(Flag(ticker, day.date(), "isolation_forest", float(row.score), severity, summary))
    return prices, tuple(flags)


def snapshot(
    ticker: str, profile: str, sensitivity_override: float | None = None
) -> tuple[pd.DataFrame, tuple[Flag, ...]]:
    """Return copied prices and immutable flags, without consulting event labels."""
    if ticker not in config.SUPPORTED_TICKERS:
        raise InputError(f"Unsupported ticker: {ticker}")
    quantile = forest_quantile(profile, sensitivity_override)
    prices, flags = _detect(
        ticker,
        quantile,
        _history_fingerprint(ticker),
        (config.MODEL_HISTORY_AS_OF, config.MONITORING_START, config.MONITORING_END),
    )
    return prices.copy(), flags


def get_flags(ticker: str, profile: str, sensitivity_override: float | None = None) -> tuple[Flag, ...]:
    return snapshot(ticker, profile, sensitivity_override)[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare ten-year histories and verify real dashboard detection.")
    parser.add_argument("--tickers", nargs="+", choices=config.SUPPORTED_TICKERS, default=config.SUPPORTED_TICKERS)
    args = parser.parse_args()
    failed = False
    for ticker in args.tickers:
        try:
            prices, flags = snapshot(ticker, "balanced")
            print(f"{ticker}: {len(prices)} price rows; {len(flags)} real flags")
        except DataError as err:
            failed = True
            print(f"{ticker}: {err}")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())

# Turn daily prices into model features. Every feature on day T uses only data up to T.
from __future__ import annotations

import numpy as np
import pandas as pd

import config

FEATURE_COLUMNS = ["ret", "abs_ret", "gap", "vol_prior", "vol_ratio"]


def build_features(prices: pd.DataFrame, window: int | None = None) -> pd.DataFrame:
    # Return one row of features per trading day, with no look-ahead.
    #
    # ret        the day's close-to-close return
    # abs_ret    absolute value of ret
    # gap        the open versus the previous close (captures overnight reactions)
    # vol_prior  standard deviation of returns over the previous `window` days (excludes day T)
    # vol_ratio  the day's volume divided by the average volume of the previous `window` days
    window = window or config.FEATURE_WINDOW
    close = prices["Close"]
    volume = prices["Volume"].astype(float)
    ret = close.pct_change()

    out = pd.DataFrame(index=prices.index)
    out["ret"] = ret
    out["abs_ret"] = ret.abs()
    out["gap"] = prices["Open"] / close.shift(1) - 1
    out["vol_prior"] = ret.shift(1).rolling(window).std()
    out["vol_ratio"] = volume / volume.shift(1).rolling(window).mean()
    return out.replace([np.inf, -np.inf], np.nan).dropna()

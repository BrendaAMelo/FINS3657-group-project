import numpy as np
import pandas as pd
import pytest

import config
from services import clients


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    # Give every test its own empty database, seeded with the demo clients.
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    clients.ensure_ready()


@pytest.fixture
def make_prices():
    # Factory for fake daily prices that look like what the app expects.

    def _make(n: int = 600, seed: int = 0, end: str = "2026-10-30") -> pd.DataFrame:
        rng = np.random.default_rng(seed)
        dates = pd.bdate_range(end=end, periods=n, name="Date")
        close = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, n)))
        open_ = close * (1 + rng.normal(0, 0.002, n))
        high = np.maximum(open_, close) * 1.002
        low = np.minimum(open_, close) * 0.998
        volume = rng.integers(900_000, 1_100_000, n).astype(float)
        return pd.DataFrame(
            {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
            index=dates,
        )

    return _make

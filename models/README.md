# Ten-year models and selected-event evaluation

Run from the repository root:

```powershell
python -m pip install -r requirements-dev.txt
python -m models.evaluate --profiles balanced
```

This single command finds the events CSV in `data/`, downloads the last ten years
of Yahoo Finance prices for its stocks, runs all three detectors and prints the
percentage of listed events detected on their exact `first_trading_day`.

## Input CSV

The default is `data/events.csv`. If that file does not exist, the script uses the
single CSV directly in `data/`. Your existing `data/FINS3657 - Events.xlsx - newData.csv`
is therefore found automatically. If several CSVs exist, choose one explicitly:

```powershell
python -m models.evaluate --events "FINS3657 - Events.xlsx - newData.csv" --profiles balanced
```

Relative filenames resolve inside `data/`, not the current working directory.
`--events data/events.csv`, absolute paths and readable Google Sheets URLs are also
supported. Private Google Sheets should be exported as CSV.

Required columns: `event_id`, `ticker`, `first_trading_day`. IDs must be nonempty
and unique; tickers must be in `config.STOCK_POOL`; dates must be `YYYY-MM-DD`.
The existing full 22-column sheet remains supported. Additional columns are kept
as metadata, example rows (`is_example=TRUE`) are excluded, and `shared_event_id`
is ignored even if missing. Stock tiers and dev/test membership are computed from
the configuration. The model input adapter no longer imposes the old 2025-2026
event window; events must instead fall within the downloaded ten-year interval.

`first_trading_day` is authoritative. The script does not substitute the announcement
date, move a holiday to another day, or give credit for a next-day alert. Weekend
dates are rejected. A weekday without a price row is reported as unscored.
The Stage D event loader uses the configured spreadsheet export and also treats shared story IDs as metadata.

## Yahoo Finance history and training

- The default end date is **yesterday in New York**, excluding a potentially
  incomplete current session. The start is exactly ten calendar years earlier.
- `--as-of 2026-11-04` requests 2016-11-04 through 2026-11-04, inclusive, so runs
  can be reproduced. The script reuses the existing Yahoo downloader and obtains
  split/dividend-adjusted daily prices and volume.
- Snapshots are cached separately in `data/cache/model_prices/START_END/`.
  Repeated runs for the same interval reuse that download; `--refresh` downloads
  it again. The old fixed 2022-2026 cache is not used for these models.
- A stock listed less than ten years ago has only its available history. Requested
  and actual coverage is recorded for every ticker in `run_metadata.json`.
- **The ten-year download is the data pool, not ten years fitted before every
  historical event.** Isolation Forest is fit/calibrated only on observations
  before the earliest event being evaluated. Using later data to fit a historical
  event detector would leak future information into its evaluation.
- Within that prior history, the earliest 80% fits the forest; the final 20%
  calibrates profile thresholds. Both end before scoring begins. The model stays
  fixed for that run. At least 100 fit and 30 calibration feature rows are required;
  otherwise its events are unscored and this is recorded. Baselines can still run.
- With `--predict-only`, the last year is scored using earlier history; no event
  metrics are calculated. In event mode, predictions run from the earliest listed
  event through the requested end date.

## The three models

All models detect anomalies at the end of a trading day. Each event's price is
the adjusted **close on `first_trading_day`**. Daily return compares that close
with the preceding available trading day's close.

| Model | Rule |
| --- | --- |
| Fixed threshold | Absolute daily return strictly greater than 5%; no fitted model |
| Rolling z-score | Absolute z-score relative to the previous 60 returns, excluding today |
| Isolation Forest | 200 trees per stock using return, absolute return, overnight gap, prior volatility and volume ratio |

Forest anomaly scores are `-score_samples`, so higher means more unusual. Scores
have different units across models and are not probabilities.

| Profile | Z-score threshold | Forest calibration percentile |
| --- | ---: | ---: |
| conservative | 2.5 | 97th |
| balanced | 3.0 | 98th |
| aggressive | 3.5 | 99th |

The fixed threshold is the same in all profiles. These settings come from
`config.PROFILES` and remain initial settings, not validated optimal thresholds.

## Evaluation: selected positives only

Your sheet contains a sample of known events, not every anomaly and not confirmed
normal days. Therefore the primary metric is **event recall / detection rate**:

```text
Event recall = events flagged on first_trading_day / listed events with usable scores
```

For example, detecting 8 of 10 scored events gives 80% recall. The report also shows
total listed events, misses, unscored events, and coverage (scored / listed). Missing
history or price dates are not silently counted as normal days or successful detections.

**Alert rate** accompanies event recall to show the volume of alerts:

```text
alert_rate = total_alerts / scored_ticker_days
alerts_per_100_days = 100 * alert_rate
```

The denominator counts one stock on one trading day as one observation, over the
prediction period (earliest evaluated event through `--as-of`), excluding unavailable
scores. All alerts count, including dates absent from the CSV and market-wide dates.
Multiple listed events on one stock/day still contribute just one alert. For example,
20 alerts over 1,000 scored stock-days is a 0.02 alert rate, or 2 per 100 stock-days.
No scored observations gives N/A; scored observations with no alerts gives zero.
Each model/profile has separate `all`, `dev` and `test` rates. This measures review
workload, not false positives. Compare recall and alert rate together.

Matching requires the same ticker and **exactly** `first_trading_day`. Market-wide
events are included. Separate event IDs on the same stock/date count as separate
listed events and can share a single detection. This is an event-weighted metric.
Anomalies outside listed dates are labelled `unlabelled`, not false positives.

TP and FN are meaningful on these positive examples. **FP, TN, precision, F1 and
overall classification accuracy cannot be estimated from this sheet** and are
shown as N/A (blank in CSV). Calling positive-event recall overall accuracy would
be misleading. The earlier stock-day confusion matrices are superseded by this method.

Results show `all`, `dev` and `test` summaries. Dev/test uses the existing
`config.SPLIT_CUTOFF` (2026-05-01) for reporting; it does not move the training cutoff
past the earliest evaluated event. Tune on dev events, then keep settings fixed for test.

## Outputs

Each evaluation also writes **`results/detected_events.json`**, independently of
`--output`. It includes only listed events flagged on their exact first trading
day by at least one model/profile selected for the run. Each ticker/date appears
once even if several models or event IDs match. `flag` is a JSON boolean and
`event_date` is the supplied `first_trading_day` in ISO format:

```json
[
  {"flag": true, "event_date": "2026-02-05", "ticker": "KO"}
]
```

The example above illustrates the schema. Each evaluation replaces this file;
no detections writes `[]`. Prediction-only mode does not export listed-event hits.
Model-specific results remain available in `event_matches.csv`.

New results default to `models/output/event_recall/`, separating them from previous
reports made under the old assumptions. `--output PATH` overrides this directory.

| File | Contents |
| --- | --- |
| `metrics.txt` | The event-recall report printed in the terminal |
| `metrics.csv` | Per model/profile/split: recall, alert rate, total alerts, scored stock-days, coverage and event counts |
| `event_matches.csv` | Every event's hit/miss/unscored status, exact-day close, return, score and threshold |
| `predictions.csv` | All scored-period dates, including non-alerts and unavailable scores |
| `alert_matches.csv` | Alerts with matching event IDs or `unlabelled` status |
| `events_snapshot.csv` | Input events used in the run; original CSV is untouched |
| `run_metadata.json` | History provenance, actual coverage, fit/calibration periods, settings and versions |

Prediction columns:

```text
date,ticker,model,profile,close_price,daily_return,score,threshold,is_anomaly,is_scored
```

`0.06` means a 6% daily return. Blank scores with `is_scored=False` mean the model
could not score that day. Infinite z-scores can occur after a perfectly flat history.

## Useful commands

```powershell
# All profiles (defaults to the tickers in the events CSV):
python -m models.evaluate

# Force a new Yahoo download:
python -m models.evaluate --profiles balanced --refresh

# Reproduce a fixed ten-year interval:
python -m models.evaluate --profiles balanced --as-of 2026-11-04

# Generate scores without an events sheet (all configured stocks by default):
python -m models.evaluate --predict-only --profiles balanced

# Tests:
python -m pytest models/tests tests -q
```

`--tickers KO AAPL` limits stocks; listed events for other stocks are explicitly
unscored. The old `--match-days` option is removed: matching is always exact-day.
The dashboard uses `services/detection.py` to run Isolation Forest over its fixed monitoring window.
`services/alerts.py` attaches prepared Stage D explanations; `services/history.py` uses the same flags for charts.
The dashboard includes unlabelled flagged days, rather than only hits exported to `results/detected_events.json`.
Its monitoring cutoff differs from this event evaluation; see the root README for the exact windows.

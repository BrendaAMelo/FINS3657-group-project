# Adviser Exception Monitor

FINS3657 Applied AI in Finance group project: a Streamlit application to help financial advisers review unusual price and trading-volume activity across client holdings, with news context and source-cited AI explanations. It supports adviser review and does not provide investment recommendations.

**Terminology.** *Stage C* is the detection-model development and evaluation work (`models/`). *Stage D* is the adviser application: news retrieval, AI explanations and the dashboard.

## Features

- Manage clients, holdings, risk profiles, and sensitivity overrides in SQLite.
- Review a consolidated alert dashboard with grouping, filtering, sorting, and saved review statuses.
- Load cached historical prices and calculate features for a configured pool of 20 US stocks.
- Retrieve relevant news from saved snapshots, remove duplicate headlines, and rank articles for explanation generation.
- Generate short explanations with source links, validation checks, and explicit `no_news` or `unavailable` fallbacks.
- Generate missing explanations automatically in the background; reuse cached results and optionally prefetch before a demonstration.

Real Isolation Forest alerts and price charts are connected to the dashboard. Cards and chart markers use the same detector, client profile, sensitivity override, and fixed monitoring period. The other two Stage C detectors remain available for evaluation.

## Installation and environment setup

Use Python 3.12 or later. Run these commands from the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

For application use without development tools, install `requirements.txt` instead. On Windows, activate the environment with `.venv\Scripts\activate`.

The main directories are:

| Directory | Purpose |
| --- | --- |
| `models/` | Anomaly detection and model evaluation |
| `services/` | Client management, alerts, news retrieval, and explanations |
| `data/` | Market data, features, validation, caches, and SQLite persistence |
| `ui/` | Streamlit pages and display helpers |
| `results/` | Saved analysis and coverage reports |
| `tests/` | Automated tests |

Dates, stock-pool settings, paths, and retrieval settings are defined in `config.py`. The configured price snapshot ends on **30 October 2026**; this is a historical demonstration rather than a live market feed.

## API key setup (.env pattern)

Copy the example file:

```bash
cp .env.example .env
```

Set the following locally, using your provider's actual values:

```dotenv
NEWS_API_KEY=your_news_api_key
LLM_BASE_URL=https://your-provider.example/v1
LLM_API_KEY=your_llm_api_key
LLM_MODEL=your_model_name
```

`NEWS_API_KEY` is used to download Finnhub news. The explanation client requires all three `LLM_*` settings and calls the provider's `/chat/completions` endpoint. 

Keep credentials out of version control. Deployed applications can use Streamlit secrets with the same names. Existing explanation cache hits do not require an LLM request, but retrieval still needs the matching news and price snapshots.

## Usage guide

### Run the application

```bash
streamlit run app.py
```

| Page | Purpose |
| --- | --- |
| **Clients** | Manage clients, holdings, risk profiles and sensitivity overrides |
| **Needs attention** | Filter, group and review historical alerts. When grouped by client, each client appears as a collapsed panel showing the filtered warning count |
| **Price charts** | Inspect adjusted prices with matching anomaly markers |
| **How it works** | In-app guidance |

Adding holdings opens **Needs attention**, shows the real alerts and any related news, and queues missing AI explanations. The page refreshes every two seconds, so explanations appear as they finish. Generation and news retrieval failures never hide an alert.

### Prepare data (only needed to rebuild caches)

```bash
python -m data.build_cache      # market prices
python -m data.sanity_check     # validate prices
python -m data.build_news       # Finnhub news snapshots
python -m services.coverage     # news coverage report
python -m services.detection    # ten-year histories for all 20 stocks
```

- Builders reuse existing caches. Add `--refresh` to `build_cache` or `build_news` to download again.
- `build_news` needs a valid `NEWS_API_KEY` and takes roughly 15-25 minutes because of rate limits.
- `services.coverage` reads the event export `data/FINS3657 - Events.xlsx - newData.csv` and writes `results/event_news_coverage.csv`. Shared story IDs are metadata; each event keeps its own first trading day.
- `services.detection` reuses existing histories. Missing ones require Yahoo Finance access. The history pool is fixed at **4 November 2026**, while displayed prices and flags end on **30 October 2026** to match the prepared news period.
- The detector is fitted and calibrated on data before **1 November 2025**, independently of the labelled events. Changing a chart's visible period does not refit it.

### Explanations and caching

- A cached explanation is matched on ticker, date, exact summary, article IDs and prompt version. Matches are reused without an LLM request.
- Missing explanations are generated in the background. Jobs are shared across clients within one application process and run one at a time to limit provider load. Running several app instances can still duplicate requests.
- Related articles are shown separately from the sources cited by a completed explanation, because relevance does not prove causation.
- Failed generations are not cached and retry after a cooldown. **Refresh and retry unavailable explanations** retries immediately without duplicating active jobs. Refresh does not download new market data.
- Generating uncached explanations needs the `LLM_*` settings and may incur provider charges.

Optional prefetching warms the cache before a demonstration:

```bash
python -m services.prefetch --alerts    # actual flags for current holdings and sensitivities
python -m services.prefetch --tickers KO AAPL NVDA --profiles conservative balanced aggressive
```

The legacy `python -m services.prefetch --events` command prepares labelled-event examples using a generic summary. These are not forced onto model alerts.

### Sensitivity and severity

Sensitivity overrides use a 2.0-4.0 scale. **Lower values are more sensitive and produce more alerts.** For Isolation Forest, the scale maps to calibration quantiles:

| Override | 2.0 | 2.5 | 3.0 | 3.5 | 4.0 |
| --- | --- | --- | --- | --- | --- |
| Threshold quantile | 95% | 97% | 98% | 99% | 99.5% |

Intermediate values are interpolated. This mapping is experimental.

Severity is a display heuristic: a score at least 1.2× its threshold is *high*, at least 1.1× is *medium*, and any other flagged score is *low*. Neither severity nor the anomaly score estimates loss or investment suitability.

## Dependencies

Runtime dependencies are pinned in `requirements.txt`: Streamlit, pandas, NumPy, scikit-learn, yfinance, requests, python-dotenv, and Altair. `requirements-dev.txt` adds pytest and Ruff.

Run the project checks from the repository root:

```bash
ruff check .
ruff format --check .
python -m pytest -q
```

## Evaluation summary

Stage C implements the fixed-return threshold, rolling z-score, and Isolation Forest detectors. A reproducible run of `python -m models.evaluate --as-of 2026-11-04` produced the reports in `models/output/event_recall/` using 23 labelled events across 14 stocks. The chronological split contains 11 development events and 12 test events. Fitting and calibration use only observations before the earliest evaluated event, **20 November 2025**.

Balanced-profile results from that run:

| Detector | Development event recall | Test event recall | Test alerts per 100 scored stock-days |
| --- | --- | --- | --- |
| Fixed return threshold | 3/11 (27.27%) | 5/12 (41.67%) | 2.53 |
| Rolling z-score | 2/11 (18.18%) | 4/12 (33.33%) | 1.37 |
| Isolation Forest | 3/11 (27.27%) | 5/12 (41.67%) | 2.36 |

**How to read these results**

- Recall is modest: the best detectors catch 5 of 12 test events (41.67%). Isolation Forest and the fixed threshold tie on recall, and no detector is clearly better.
- With 12 test events, one event changes recall by about 8 percentage points, so small differences are not meaningful.
- These are recall and workload measures on selected positive events. They are not accuracy or false-positive rates. Precision, F1 and true negatives cannot be estimated without labelled negatives.
- Profile settings are initial settings, not demonstrated optimal thresholds.
- Full per-profile results, per-event matches and provenance are in `results/model_evaluation_metrics.csv`, `results/model_event_matches.csv` and `results/model_evaluation_metadata.json`. Larger prediction files are git-ignored and can be regenerated with the command above.

**Dashboard versus evaluation.** The dashboard configuration differs from the event evaluation, so the table above is not a performance claim for the dashboard.

| | Event evaluation | Dashboard |
| --- | --- | --- |
| Fit and calibration | Before 20 Nov 2025 | Before 1 Nov 2025 |
| Scored data | 23 labelled events | 1 Nov 2025 - 30 Oct 2026, all 20 stocks |
| Thresholds | Balanced profile | Client profile plus overrides |
| Severity labels | Not applicable | Experimental |

The dashboard does not filter alerts to known event hits and does not read `results/detected_events.json`.

The original labelled-event Stage D artifacts show:

| Artifact | Observed outcome | Interpretation |
| --- | --- | --- |
| `results/event_news_coverage.csv` | 23 labelled events; all 23 classified as `heavy` news coverage, with 20–462 distinct relevant articles per event | News is available around the selected events; this does not establish detection performance or explanation accuracy. |
| Original event-prefetch entries in `data/cache/explanations/` | 23 cached explanations using prompt version `v2`: 22 `ok`, 1 `no_news` | 22 generated explanations passed the implemented checks; one returned “No clear news found for this move.” These statuses are not independent factual-quality scores. |

Coverage counts run from each event's announcement date to three trading days after its first trading day, after relevance filtering and de-duplication but before the eight-article limit. Explanation retrieval normally starts one trading day before the flagged day.

**Explanation caveats**

- Passing the implemented checks (structure, citation indices, text guardrails) is not a factual-quality rating.
- All 23 events have heavy coverage, so sparse-news behaviour is untested; the coverage check targets at least two such events.
- A `no_news` result despite heavy coverage means the pipeline found no clear explanation, not that no articles existed.
- The news window includes articles published after the flagged day, so explanations are retrospective. Such articles must not influence features, thresholds or claims about what was known at alert time.

## Known issues

- **Historical coverage:** results depend on saved snapshots. Finnhub's free tier covers about one year of news, so older articles that were not saved cannot be recovered.
- **Limited stock universe:** 20 US stocks. Findings may not generalise to other companies, markets or asset classes.
- **No automatic onboarding:** new tickers are rejected. Adding one needs data download, validation, news aliases, model fitting and explanation preparation, which is a developer task.
- **Historical, not daily, monitoring:** prices end on 30 October 2026 and nothing refreshes automatically. Features use daily closes, so there is no intraday detection.
- **Limited feedback loop:** review statuses record workflow progress, not whether an alert or explanation was useful or wrong.
- **Explanation uncertainty:** relevant articles and valid citations do not establish causation, and the news window includes post-flag articles.
- **No authentication:** The application uses a shared workspace without adviser authentication or separation of client records. Users accessing the same deployment can view and modify the same clients, holdings, and review statuses.
- **Anomaly scores are not financial-risk measures:** unusual price or volume activity does not establish that a holding is unsuitable or that action is required. Client risk profiles adjust monitoring sensitivity rather than provide a full suitability assessment.
- **Limited portfolio context:** stock-level alerts do not quantify portfolio exposure, concentration, or the monetary impact of a move. A highly unusual move in a small position may matter less than a moderate move in a large position.
- **Potentially repetitive alerts:** related moves across stocks, clients, or consecutive days can generate multiple warnings about the same underlying event. This creates a risk of alert fatigue rather than an established measured outcome.
- **Model stability requires reassessment:** historical relationships and thresholds may become less appropriate as market conditions change. There is no scheduled drift-monitoring or retraining workflow.
- **Limited evaluation representativeness:** the labelled event set and observation period cannot establish performance across all market conditions. The current news coverage report contains only heavily reported events, and explanation statuses are not independent quality ratings. Model performance remains subject to Stage C evaluation.
- **Prototype operational resilience:** local SQLite storage and file caches do not provide an implemented backup-and-restore workflow, coordinated background jobs, or conflict detection for simultaneous edits. Larger deployments would require further operational testing; no concurrent-user capacity is claimed.

## Planned future enhancements

1. Scheduled daily updates (prices, news, features, detection, explanations) with data-freshness indicators and failure reporting.
2. Controlled stock onboarding with explicit readiness states (history, validation, news aliases, evaluation).
3. Ongoing news archiving and additional data sources for longer history.
4. Adviser accounts, ownership checks in the service layer and an audit trail, before any real client data is used.
5. Structured feedback on alert usefulness, false positives and explanation quality, to support reviewed threshold changes.
6. An alert-time explanation mode with a publication-time cutoff, alongside labelled retrospective explanations.
7. Portfolio-aware prioritisation using position values, weights and concentration, with the original anomaly score kept visible.
8. Broader evaluation across stocks, regimes and sparse-news events, with human review of explanation quality.
9. Distinguish statistical unusualness from financial impact in alert wording, and explain what sensitivity settings and anomaly scores mean without presenting them as suitability judgments or probabilities of loss.
10. Group related alerts across stocks and dates, reuse shared event context across clients, and offer adviser-controlled digests to reduce repetitive review.
11. Monitor score distributions, alert frequency, and data quality over time; reassess models through chronological validation before approving retraining or threshold changes.
12. Add tested backups and recovery, coordinated background processing, conflict detection, and load testing; assess a server database if deployment requirements justify it.
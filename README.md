# Adviser Exception Monitor

FINS3657 Applied AI in Finance group project: a Streamlit application to help financial advisers review unusual price and trading-volume activity across client holdings, with news context and source-cited AI explanations. It supports adviser review and does not provide investment recommendations.

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

Start the application:

```bash
streamlit run app.py
```

Use **Clients** to manage clients, holdings, profiles, and sensitivity. Use **Needs attention** to filter and review real historical alerts, and **Price charts** to inspect adjusted prices and matching anomaly markers. **How it works** provides application guidance.

To prepare data and Stage D artifacts:

```bash
python -m data.build_cache
python -m data.sanity_check
python -m data.build_news
python -m services.coverage
python -m services.detection
```

The builders reuse existing caches; add `--refresh` to either builder to download again. News downloads require a valid key and can take approximately 15–25 minutes because of rate limits. Generating uncached explanations requires the LLM settings above and may incur provider charges.

`services.coverage` writes `results/event_news_coverage.csv`. The event export is configured as `data/FINS3657 - Events.xlsx - newData.csv`; Shared story IDs are metadata, and each event retains its own first trading day.

`services.detection` prepares/verifies ten-year histories for all 20 supported stocks using Stage C's history loader. Existing histories are reused; missing ones require Yahoo Finance access. The history pool is fixed at **4 November 2026**, while displayed prices and flags end on **30 October 2026** to align with the prepared news period. Fitting and calibration finish before **1 November 2025**, independently of the labelled event list. Changing a chart's visible period does not refit the detector.

Adding holdings automatically opens **Needs attention**, displays real alerts and available related news, and queues missing AI explanations. The page updates every two seconds while open, so explanations appear as they finish. Generation uses the configured LLM provider; uncached explanations take time, and failures do not hide alerts. News remains drawn from the prepared historical snapshot.

Prefetch is optional: `python -m services.prefetch --alerts` warms the cache for actual flags belonging to current client holdings and sensitivity settings. It deduplicates shared ticker/date/summary inputs across clients. To prepare a larger demo pool before adding clients, use, for example:

```bash
python -m services.prefetch --tickers KO AAPL NVDA --profiles conservative balanced aggressive
```

The legacy `python -m services.prefetch --events` command prepares labelled-event examples using a generic summary. These examples are not forced onto model alerts. Explanation cache matching depends on ticker, date, exact summary, article IDs, and prompt version. The dashboard reuses matching cached explanations and automatically generates missing ones. Jobs are shared across clients in the same application process and run one at a time to limit provider load. Available related articles are shown separately from citations supporting a completed explanation. Failed generations can retry after a cooldown; **Refresh and retry unavailable explanations** requests another attempt immediately without duplicating active jobs. No terminal command is required after changing holdings or sensitivity. Refresh does not download new market snapshots.

Lower sensitivity overrides produce more alerts. For Isolation Forest, the UI's 2.0–4.0 scale is interpolated to calibration quantiles: 2.0 maps to 95%, configured profiles supply the intermediate anchors (2.5/97%, 3.0/98%, 3.5/99%), and 4.0 maps to 99.5%. This mapping is experimental. Severity is a display heuristic: scores at least 1.2 times their threshold are high, at least 1.1 times are medium, and remaining flagged scores are low. Neither severity nor anomaly scores estimate loss or investment suitability.

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

All listed events had usable scores in this run. Matching requires the same ticker on the **exact first trading day**, without adjacent-day credit. These are recall and workload measures on selected positive events, not overall accuracy or false-positive rates; precision, F1, and true negatives cannot be estimated without labelled negatives. Profile settings are initial settings, not demonstrated optimal thresholds. Full profile/split results, per-event matches, and provenance are preserved in `results/model_evaluation_metrics.csv`, `results/model_event_matches.csv`, and `results/model_evaluation_metadata.json`. The larger prediction files remain in the ignored local output directory and can be regenerated with the command above.

The dashboard intentionally scores a fixed **1 November 2025–30 October 2026** window for all 20 supported stocks. Its fit cutoff, displayed window, experimental severity labels, and custom overrides differ from the event-evaluation run, so the table is not a measured performance claim for every dashboard configuration. The dashboard does not filter alerts to known event hits or read `results/detected_events.json` as its alert feed.

The original labelled-event Stage D artifacts show:

| Artifact | Observed outcome | Interpretation |
| --- | --- | --- |
| `results/event_news_coverage.csv` | 23 labelled events; all 23 classified as `heavy` news coverage, with 20–462 distinct relevant articles per event | News is available around the selected events; this does not establish detection performance or explanation accuracy. |
| Original event-prefetch entries in `data/cache/explanations/` | 23 cached explanations using prompt version `v2`: 22 `ok`, 1 `no_news` | 22 generated explanations passed the implemented checks; one returned “No clear news found for this move.” These statuses are not independent factual-quality scores. |

Coverage counts use the period from the event's announcement date through three trading days after its first trading day. Counts are taken after relevance filtering and deduplication, before limiting the articles sent to the language model. Explanation retrieval normally starts one trading day before the flagged day and supplies at most eight articles.

The explanation pipeline checks response structure, citation indices, and text guardrails. Missing coverage or generation failures return `unavailable`; failures are not persistently cached so later calls can retry. Automated checks and cache statuses alone do not establish that an explanation correctly identifies the cause of a market move.

**News limitations:** the current coverage report has no sparse-news or no-news events, so it does not meet the coverage check's target of at least two such events. A `no_news` explanation despite heavy article coverage means the pipeline did not identify a clear explanation, rather than that no articles existed. Further explanation-quality review and evaluation on sparse-news cases remain necessary.

The Stage D news window includes articles published after the flagged day and therefore supports retrospective explanations. Those later articles must not influence model features, threshold selection, or claims about information available at alert time. An alert-time explanation mode would need a publication-time cutoff.

## Known issues

- **Finite historical coverage:** analysis depends on saved price and news snapshots. Finnhub's free-tier company news history is limited to approximately the past year, restricting retrospective analysis and recovery of older articles not already saved. Provider coverage and API limits also affect data availability.
- **Limited stock universe:** the configured pool contains 20 US stocks. Findings cannot be assumed to generalise to other companies, markets, or asset classes.
- **No automatic onboarding of new stocks:** advisers can manage holdings, but adding a ticker does not trigger an end-to-end workflow to download and validate its data, configure news aliases, fit and evaluate detection models, and prepare explanations. Monitoring depends on the prepared stock pool.
- **Historical rather than daily monitoring:** the application uses a fixed market-data snapshot. It does not automatically refresh prices and news, rerun detection each trading day, or deliver live notifications.
- **Limited feedback loop:** saved review statuses support adviser workflow, but they do not capture structured judgments about false alerts or explanation quality and do not update model settings automatically.
- **Explanation uncertainty:** relevant articles and valid citations do not establish what caused a market move. Sparse reporting, incomplete summaries, and language-model errors can limit explanation quality. The retrospective news window can include articles published after the flagged day.

## Planned future enhancements

1. Introduce scheduled daily updates for prices and news, followed by feature calculation, detection, and explanation generation, with visible data-freshness indicators and update-failure reporting.
2. Expand the stock universe and add an onboarding workflow for adviser-requested tickers, including data validation, news configuration, and model evaluation before marking a stock as supported.
3. Extend historical coverage through ongoing archiving and additional or paid data sources, enabling evaluation across more market conditions and longer periods.
4. Capture structured adviser feedback on alert usefulness, false positives, and explanation quality to support reviewed threshold changes and periodic model reassessment.
5. Add an alert-time explanation mode that only uses news available when the alert was raised, alongside clearly labelled retrospective explanations.
6. Broaden evaluation across stocks, market conditions, and sparse-news cases, including human review of explanation support and usefulness.


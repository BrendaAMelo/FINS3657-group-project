# Adviser Exception Monitor

FINS3657 Applied AI in Finance group project: a Streamlit application to help financial advisers review unusual price and trading-volume activity across client holdings, with news context and source-cited AI explanations. It supports adviser review and does not provide investment recommendations.

## Features

- Manage clients, holdings, risk profiles, and sensitivity overrides in SQLite.
- Review a consolidated alert dashboard with grouping, filtering, sorting, and saved review statuses.
- Load cached historical prices and calculate features for a configured pool of 20 US stocks.
- Retrieve relevant news from saved snapshots, remove duplicate headlines, and rank articles for explanation generation.
- Generate short explanations with source links, validation checks, and explicit `no_news` or `unavailable` fallbacks.
- Cache explanations and prefetch them before a demonstration.

Model-driven alerts and price-chart integration are planned for Stage E. The chart page is currently disabled.

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

Use **Clients** to manage clients, holdings, profiles, and sensitivity. Use **Needs attention** to filter and review the current demonstration alerts. **How it works** provides application guidance. 

To prepare data and Stage D artifacts:

```bash
python -m data.build_cache
python -m data.sanity_check
python -m data.build_news
python -m services.coverage
python -m services.prefetch --events
```

The builders reuse existing caches; add `--refresh` to either builder to download again. News downloads require a valid key and can take approximately 15–25 minutes because of rate limits. Generating uncached explanations requires the LLM settings above and may incur provider charges.

`services.coverage` writes `results/event_news_coverage.csv`. The current prefetch command generates explanations for the labelled events in `data/events.csv`, using a standard summary. It does not run an anomaly detector or populate the dashboard with real alerts.

After Stage C, Stage E must pass actual detected `(ticker, date, summary)` values into the explanation pipeline and prefetch those alerts before the demo. Cache matching depends on ticker, date, exact summary, retrieved article IDs, and prompt version. Existing event explanations are reused only when those inputs match; other flags need new entries.

## Dependencies

Runtime dependencies are pinned in `requirements.txt`: Streamlit, pandas, NumPy, scikit-learn, yfinance, requests, python-dotenv, and Altair. `requirements-dev.txt` adds pytest and Ruff.

Run the project checks from the repository root:

```bash
ruff check .
ruff format --check .
python -m pytest -q
```

## Evaluation summary

**This is a Stage D progress summary only. The core anomaly-detection evaluation still needs to be completed in Stage C. No model accuracy, event-detection performance, false-alert rate, or detector comparison is reported here.**

The currently saved Stage D artifacts show:

| Artifact | Observed outcome | Interpretation |
| --- | --- | --- |
| `results/event_news_coverage.csv` | 23 labelled events; all 23 classified as `heavy` news coverage, with 20–462 distinct relevant articles per event | News is available around the selected events; this does not establish detection performance or explanation accuracy. |
| `data/cache/explanations/` | 23 cached explanations using prompt version `v2`: 22 `ok`, 1 `no_news` | 22 generated explanations passed the implemented checks; one returned “No clear news found for this move.” These statuses are not independent factual-quality scores. |

Coverage counts use the period from the event's announcement date through three trading days after its first trading day. Counts are taken after relevance filtering and deduplication, before limiting the articles sent to the language model. Explanation retrieval normally starts one trading day before the flagged day and supplies at most eight articles.

The explanation pipeline checks response structure, citation indices, and text guardrails. Missing coverage or generation failures return `unavailable`; failures are not persistently cached so later calls can retry. Automated checks and cache statuses alone do not establish that an explanation correctly identifies the cause of a market move.

**News limitations:** the current coverage report has no sparse-news or no-news events, so it does not meet the coverage check's target of at least two such events. A `no_news` explanation despite heavy article coverage means the pipeline did not identify a clear explanation, rather than that no articles existed. Further explanation-quality review and evaluation on sparse-news cases remain necessary.

**Stage C evaluation still required:** implement and compare the fixed-return threshold, rolling z-score, and Isolation Forest detectors; select settings using development data; then evaluate on the chronological held-out period. The configured event split is before **1 May 2026** for development and on/after that date for testing, with an event match window of the first trading day through the following trading day. Report detection results, false-alert behaviour, and limitations only after the evaluation has actually run. Current profile thresholds are placeholders.

The Stage D news window includes articles published after the flagged day and therefore supports retrospective explanations. Those later articles must not influence model features, threshold selection, or claims about information available at alert time. An alert-time explanation mode would need a publication-time cutoff.

## Known issues

- **Finite historical coverage:** analysis depends on saved price and news snapshots. Finnhub's free-tier company news history is limited to approximately the past year, restricting retrospective analysis and recovery of older articles not already saved. Provider coverage and API limits also affect data availability.
- **Limited stock universe:** the configured pool contains 20 US stocks. Findings cannot be assumed to generalise to other companies, markets, or asset classes.
- **No automatic onboarding of new stocks:** advisers can manage holdings, but adding a ticker does not trigger an end-to-end workflow to download and validate its data, configure news aliases, fit and evaluate detection models, and prepare explanations. Monitoring depends on the prepared stock pool.
- **Historical rather than daily monitoring:** the application uses a fixed market-data snapshot. It does not automatically refresh prices and news, rerun detection each trading day, or deliver live notifications.
- **Limited feedback loop:** saved review statuses support adviser workflow, but they do not capture structured judgments about false alerts or explanation quality and do not update model settings automatically.
- **Explanation uncertainty:** relevant articles and valid citations do not establish what caused a market move. Sparse reporting, incomplete summaries, and language-model errors can limit explanation quality. The retrospective news window can include articles published after the flagged day.
- **No authentication:** The application uses a shared workspace without adviser authentication or separation of client records. Users accessing the same deployment can view and modify the same clients, holdings, and review statuses.
- **Anomaly scores are not financial-risk measures:** unusual price or volume activity does not establish that a holding is unsuitable or that action is required. Client risk profiles adjust monitoring sensitivity rather than provide a full suitability assessment.
- **Limited portfolio context:** stock-level alerts do not quantify portfolio exposure, concentration, or the monetary impact of a move. A highly unusual move in a small position may matter less than a moderate move in a large position.
- **Potentially repetitive alerts:** related moves across stocks, clients, or consecutive days can generate multiple warnings about the same underlying event. This creates a risk of alert fatigue rather than an established measured outcome.
- **Model stability requires reassessment:** historical relationships and thresholds may become less appropriate as market conditions change. There is no scheduled drift-monitoring or retraining workflow.
- **Limited evaluation representativeness:** the labelled event set and observation period cannot establish performance across all market conditions. The current news coverage report contains only heavily reported events, and explanation statuses are not independent quality ratings. Model performance remains subject to Stage C evaluation.
- **Prototype operational resilience:** local SQLite storage and file caches do not provide an implemented backup-and-restore workflow, coordinated background jobs, or conflict detection for simultaneous edits. Larger deployments would require further operational testing; no concurrent-user capacity is claimed.

## Planned future enhancements

1. Introduce scheduled daily updates for prices and news, followed by feature calculation, detection, and explanation generation, with visible data-freshness indicators and update-failure reporting.
2. Expand the stock universe and add an onboarding workflow for adviser-requested tickers, including data validation, news configuration, and model evaluation before marking a stock as supported.
3. Extend historical coverage through ongoing archiving and additional or paid data sources, enabling evaluation across more market conditions and longer periods.
4. Capture structured adviser feedback on alert usefulness, false positives, and explanation quality to support reviewed threshold changes and periodic model reassessment.
5. Add an alert-time explanation mode that only uses news available when the alert was raised, alongside clearly labelled retrospective explanations.
6. Broaden evaluation across stocks, market conditions, and sparse-news cases, including human review of explanation support and usefulness.
7. Introduce adviser accounts, ownership-based access controls, and an audit trail before supporting independent advisers or real client data.
8. Distinguish statistical unusualness from financial impact in alert wording, and explain what sensitivity settings and anomaly scores mean without presenting them as suitability judgments or probabilities of loss.
9. Incorporate position values, portfolio weights, and concentration measures into alert prioritisation while retaining the original anomaly score.
10. Group related alerts across stocks and dates, reuse shared event context across clients, and offer adviser-controlled digests to reduce repetitive review.
11. Monitor score distributions, alert frequency, and data quality over time; reassess models through chronological validation before approving retraining or threshold changes.
12. Add tested backups and recovery, coordinated background processing, conflict detection, and load testing; assess a server database if deployment requirements justify it.


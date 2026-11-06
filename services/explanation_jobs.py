"""Generate missing explanations in the background, shared across client sessions.

Workers never render Streamlit UI. The UI polls immutable results; disk caching remains
the durable source of successful explanations. One worker limits provider load.
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import date
from threading import Lock

import config
from services import explain as explanation_service
from services.contracts import Explanation

log = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="news-explanations")
_lock = Lock()
RETRY_SECONDS = 60
MAX_FINISHED_JOBS = 256


@dataclass
class Job:
    future: Future[Explanation]
    retry_at: float | None = None


_jobs: OrderedDict[tuple, Job] = OrderedDict()


def _key(ticker: str, day: date, summary: str) -> tuple:
    path = config.NEWS_CACHE_DIR / f"{ticker}.json.gz"
    return (
        ticker,
        day,
        summary,
        config.PROMPT_VERSION,
        str(config.EXPLANATION_CACHE_DIR),
        str(path),
        path.stat().st_mtime_ns if path.exists() else None,
    )


def _generate(ticker: str, day: date, summary: str) -> Explanation:
    try:
        return explanation_service.explain(ticker, day, summary)
    except Exception:
        # A worker failure must never remove the underlying price alert.
        log.exception("Background explanation failed for %s on %s", ticker, day)
        return Explanation(explanation_service.UNAVAILABLE_TEXT, "unavailable")


def explain(ticker: str, day: date, summary: str) -> Explanation:
    preview = explanation_service.explain(ticker, day, summary, generate=False)
    if preview.status != "pending":
        return preview  # A cache hit or insufficient news needs no provider request.
    key = _key(ticker, day, summary)
    with _lock:
        job = _jobs.get(key)
        if job is not None:
            _jobs.move_to_end(key)
            if not job.future.done():
                return preview
            result = job.future.result()
            if result.status != "ok" and not result.related_news:
                result = replace(result, related_news=preview.related_news)
            if result.status != "unavailable":
                return result
            if job.retry_at is None:
                job.retry_at = time.monotonic() + RETRY_SECONDS
            if time.monotonic() < job.retry_at:
                return result
            del _jobs[key]
        # Keep active jobs even when the completed-result budget is exhausted.
        finished = [k for k, value in _jobs.items() if value.future.done()]
        for old_key in finished[: max(0, len(finished) - MAX_FINISHED_JOBS + 1)]:
            del _jobs[old_key]
        _jobs[key] = Job(_executor.submit(_generate, ticker, day, summary))
    return preview


def retry_failed() -> None:
    """An explicit refresh can retry failed jobs, without duplicating active work."""
    with _lock:
        for key, job in list(_jobs.items()):
            if job.future.done() and job.future.result().status == "unavailable":
                del _jobs[key]

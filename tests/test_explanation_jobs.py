from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, date, datetime

import pytest

import config
from data.news import Article
from services import alerts, clients, detection, explain
from services import explanation_jobs as jobs
from services.contracts import Explanation
from services.retrieval import Retrieved
from ui import cached

DAY = date(2026, 3, 12)
SUMMARY = "Unusual price and volume features."


class ControlledExecutor:
    def __init__(self):
        self.tasks = []

    def submit(self, function, *args):
        future = Future()
        self.tasks.append((future, function, args))
        return future

    def finish(self, index=0):
        future, function, args = self.tasks[index]
        future.set_result(function(*args))


@pytest.fixture
def prepared(monkeypatch, tmp_path):
    executor = ControlledExecutor()
    monkeypatch.setattr(jobs, "_executor", executor)
    monkeypatch.setattr(jobs, "_jobs", OrderedDict())
    monkeypatch.setattr(config, "EXPLANATION_CACHE_DIR", tmp_path / "explanations")
    monkeypatch.setattr(config, "NEWS_CACHE_DIR", tmp_path / "news")
    article = Article(
        "1",
        "KO",
        datetime(2026, 3, 12, 15, tzinfo=UTC),
        "Coca-Cola reported quarterly results",
        "",
        "Wire",
        "https://example.com/news",
    )
    found = Retrieved("KO", DAY, DAY, (article,), 1, True)
    monkeypatch.setattr(explain.retrieval, "retrieve", lambda *args: found)
    calls = []

    def complete(*args):
        calls.append(args)
        return '{"explains_move": true, "explanation": "Coca-Cola reported quarterly results.", "cited": [1]}'

    monkeypatch.setattr(explain.llm, "complete", complete)
    return executor, calls


def test_new_holdings_show_alerts_and_news_then_automatic_explanations(monkeypatch, prepared):
    executor, calls = prepared
    client = clients.add_client("Automatic", "balanced")
    client = clients.add_holding(client.client_id, "KO")
    flag = detection.Flag("KO", DAY, "isolation_forest", 0.7, "high", SUMMARY)
    monkeypatch.setattr(detection, "get_flags", lambda *args: (flag,))
    pending = cached.alerts_for(client)
    assert len(pending) == 1 and pending[0].explanation_status == "pending"
    assert pending[0].related_news[0].url == "https://example.com/news"
    assert pending[0].sources == ()  # Related news is not yet a causal citation.
    assert calls == []  # The UI did not wait for the provider.
    executor.finish()
    ready = cached.alerts_for(client)
    assert ready[0].explanation_status == "ok"
    assert ready[0].sources[0].url == "https://example.com/news"
    assert len(calls) == 1
    another = clients.add_client("Another", "balanced")
    clients.add_holding(another.client_id, "KO")
    assert alerts.get_alerts(another.client_id)[0].explanation_status == "ok"
    assert len(executor.tasks) == 1 and len(calls) == 1


def test_concurrent_clients_share_one_pending_job(prepared):
    executor, calls = prepared
    with ThreadPoolExecutor(max_workers=3) as requesters:
        results = list(requesters.map(lambda _: jobs.explain("KO", DAY, SUMMARY), range(3)))
    assert all(r.status == "pending" for r in results)
    assert len(executor.tasks) == 1 and calls == []


def test_failed_jobs_have_cooldown_and_refresh_preserves_active_jobs(monkeypatch, prepared):
    executor, _ = prepared
    now = [0.0]
    monkeypatch.setattr(jobs.time, "monotonic", lambda: now[0])
    jobs.explain("KO", DAY, SUMMARY)
    executor.tasks[0][0].set_result(Explanation("Unavailable.", "unavailable"))
    assert jobs.explain("KO", DAY, SUMMARY).status == "unavailable"
    now[0] = jobs.RETRY_SECONDS - 1
    assert jobs.explain("KO", DAY, SUMMARY).status == "unavailable"
    assert len(executor.tasks) == 1
    now[0] += 1
    assert jobs.explain("KO", DAY, SUMMARY).status == "pending"
    jobs.retry_failed()
    jobs.explain("KO", DAY, SUMMARY)
    assert len(executor.tasks) == 2
    executor.tasks[1][0].set_result(Explanation("Unavailable.", "unavailable"))
    jobs.retry_failed()
    assert jobs.explain("KO", DAY, SUMMARY).status == "pending"
    assert len(executor.tasks) == 3


def test_insufficient_news_does_not_schedule_generation(monkeypatch, prepared):
    executor, _ = prepared
    monkeypatch.setattr(explain.retrieval, "retrieve", lambda *args: Retrieved("KO", DAY, DAY, (), 0, False))
    assert jobs.explain("KO", DAY, SUMMARY).status == "unavailable"
    assert executor.tasks == []


def test_worker_failure_becomes_fallback(monkeypatch, prepared):
    executor, _ = prepared
    jobs.explain("KO", DAY, SUMMARY)

    def broken(*args, **kwargs):
        raise RuntimeError("Unexpected provider failure")

    monkeypatch.setattr(explain, "explain", broken)
    executor.finish()
    assert executor.tasks[0][0].result().status == "unavailable"

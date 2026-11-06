from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, date, datetime

import pytest
from streamlit.testing.v1 import AppTest

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


def test_new_holdings_only_generate_explanations_on_explicit_refresh(monkeypatch, prepared):
    executor, calls = prepared
    client = clients.add_client("Automatic", "balanced")
    client = clients.add_holding(client.client_id, "KO")
    flag = detection.Flag("KO", DAY, "isolation_forest", 0.7, "high", SUMMARY)
    monkeypatch.setattr(detection, "get_flags", lambda *args: (flag,))
    idle = cached.alerts_for(client)
    assert idle[0].explanation_status == "unavailable"
    assert "Click Refresh dashboard" in idle[0].explanation
    assert executor.tasks == [] and calls == []
    pending = cached.alerts_for(client, generate_explanations=True)
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
        results = list(requesters.map(lambda _: jobs.explain("KO", DAY, SUMMARY, generate=True), range(3)))
    assert all(r.status == "pending" for r in results)
    assert len(executor.tasks) == 1 and calls == []


def test_failed_jobs_only_retry_on_explicit_refresh(prepared):
    executor, _ = prepared
    jobs.explain("KO", DAY, SUMMARY, generate=True)
    executor.tasks[0][0].set_result(Explanation("Unavailable.", "unavailable"))
    for _ in range(5):
        assert jobs.explain("KO", DAY, SUMMARY).status == "unavailable"
    assert len(executor.tasks) == 1
    cached.clear_data()
    # Clearing a failure alone must not make read-only views start another job.
    assert jobs.explain("KO", DAY, SUMMARY).status == "unavailable"
    assert len(executor.tasks) == 1
    assert jobs.explain("KO", DAY, SUMMARY, generate=True).status == "pending"
    assert len(executor.tasks) == 2
    cached.clear_data()
    assert jobs.explain("KO", DAY, SUMMARY, generate=True).status == "pending"
    assert len(executor.tasks) == 2  # An active job is shared across refreshes.
    executor.tasks[1][0].set_result(Explanation("Unavailable.", "unavailable"))
    cached.clear_data()
    assert jobs.explain("KO", DAY, SUMMARY, generate=True).status == "pending"
    assert len(executor.tasks) == 3


def test_insufficient_news_does_not_schedule_generation(monkeypatch, prepared):
    executor, _ = prepared
    monkeypatch.setattr(explain.retrieval, "retrieve", lambda *args: Retrieved("KO", DAY, DAY, (), 0, False))
    assert jobs.explain("KO", DAY, SUMMARY, generate=True).status == "unavailable"
    assert executor.tasks == []


def test_worker_failure_becomes_fallback(monkeypatch, prepared):
    executor, _ = prepared
    jobs.explain("KO", DAY, SUMMARY, generate=True)

    def broken(*args, **kwargs):
        raise RuntimeError("Unexpected provider failure")

    monkeypatch.setattr(explain, "explain", broken)
    executor.finish()
    assert executor.tasks[0][0].result().status == "unavailable"


def test_ui_only_schedules_ai_from_dashboard_refresh(monkeypatch, prepared):
    executor, calls = prepared
    client = clients.add_client("Manual refresh", "balanced")
    clients.add_holding(client.client_id, "KO")
    flag = detection.Flag("KO", DAY, "isolation_forest", 0.7, "high", SUMMARY)
    monkeypatch.setattr(detection, "get_flags", lambda *args: (flag,))

    def clients_page():
        from ui.views import clients

        clients.render()

    def alerts_page():
        from ui.views import alerts

        alerts.render()

    manage = AppTest.from_function(clients_page, default_timeout=15).run()
    manage.run()
    assert not manage.exception
    assert executor.tasks == [] and calls == []

    dashboard = AppTest.from_function(alerts_page, default_timeout=15).run()
    assert not dashboard.exception
    assert executor.tasks == []
    dashboard.button[0].click().run()
    assert not dashboard.exception
    assert len(executor.tasks) == 1

    assert not dashboard.metric and not dashboard.text_input
    assert dashboard.button[0].disabled
    dashboard.run()
    manage.run()
    assert not dashboard.exception and not manage.exception
    assert len(executor.tasks) == 1 and calls == []

    executor.finish()
    dashboard.run()
    assert not dashboard.exception
    assert dashboard.metric
    assert not dashboard.button[0].disabled
    assert any("Coca-Cola reported quarterly results" in item.value for item in dashboard.markdown)
    assert len(executor.tasks) == 1 and len(calls) == 1

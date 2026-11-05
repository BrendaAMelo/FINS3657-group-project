import pytest
import requests

import config
from services import llm


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda _seconds: None)
    monkeypatch.setenv("LLM_BASE_URL", "https://api.example.com/v1/")
    monkeypatch.setenv("LLM_API_KEY", "secret-key")
    monkeypatch.setenv("LLM_MODEL", "test-model")


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload
        self.text = "error text"

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def install_fake_post(monkeypatch, responses):
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        item = responses[min(len(calls) - 1, len(responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(llm.requests, "post", fake_post)
    return calls


def ok(text=" hello "):
    return FakeResponse(payload={"choices": [{"message": {"content": text}}]})


def test_successful_call_builds_the_request_correctly(monkeypatch):
    calls = install_fake_post(monkeypatch, [ok()])
    assert llm.complete("system text", "user text") == "hello"
    call = calls[0]
    assert call["url"] == "https://api.example.com/v1/chat/completions"
    assert call["headers"] == {"Authorization": "Bearer secret-key"}
    assert call["timeout"] == config.LLM_TIMEOUT_SECONDS
    assert call["json"]["model"] == "test-model"
    assert [m["role"] for m in call["json"]["messages"]] == ["system", "user"]


def test_not_configured_fails_before_any_request(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY")
    calls = install_fake_post(monkeypatch, [ok()])
    with pytest.raises(llm.LLMUnavailableError):
        llm.complete("s", "u")
    assert calls == []


def test_plain_http_is_refused_so_the_key_is_never_sent_in_clear(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://example.com/v1")
    calls = install_fake_post(monkeypatch, [ok()])
    with pytest.raises(llm.LLMUnavailableError):
        llm.complete("s", "u")
    assert calls == []


def test_rejected_key_is_not_retried(monkeypatch):
    calls = install_fake_post(monkeypatch, [FakeResponse(status=401)])
    with pytest.raises(llm.LLMUnavailableError):
        llm.complete("s", "u")
    assert len(calls) == 1


def test_rate_limit_is_retried(monkeypatch):
    calls = install_fake_post(monkeypatch, [FakeResponse(status=429), ok("fine")])
    assert llm.complete("s", "u") == "fine"
    assert len(calls) == 2


def test_bad_request_is_reported_without_retrying(monkeypatch):
    calls = install_fake_post(monkeypatch, [FakeResponse(status=400)])
    with pytest.raises(llm.LLMUnavailableError) as exc:
        llm.complete("s", "u")
    assert "400" in str(exc.value) and len(calls) == 1


def test_network_failure_gives_up_after_the_retries(monkeypatch):
    calls = install_fake_post(monkeypatch, [requests.exceptions.ConnectionError("down")])
    with pytest.raises(llm.LLMUnavailableError):
        llm.complete("s", "u")
    assert len(calls) == config.LLM_RETRIES


@pytest.mark.parametrize(
    "payload", [{}, {"choices": []}, {"choices": [{"message": {"content": None}}]}, ValueError("x")]
)
def test_unexpected_replies_are_reported(monkeypatch, payload):
    install_fake_post(monkeypatch, [FakeResponse(payload=payload)])
    with pytest.raises(llm.LLMUnavailableError):
        llm.complete("s", "u")

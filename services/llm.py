# A small, provider-neutral client for OpenAI-style /chat/completions endpoints.
from __future__ import annotations

import logging
import time

import requests

import config

log = logging.getLogger(__name__)


class LLMUnavailableError(Exception):
    """The language model could not be used. The message is safe to log."""


def _endpoint(base_url: str) -> str:
    base = base_url.strip().rstrip("/")
    local = base.startswith(("http://localhost", "http://127.0.0.1"))
    if not (base.startswith("https://") or local):  # never send the key over plain http
        raise LLMUnavailableError("LLM_BASE_URL must start with https://.")
    return f"{base}/chat/completions"


def _content(response: requests.Response) -> str:
    try:
        return response.json()["choices"][0]["message"]["content"].strip()
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as err:
        raise LLMUnavailableError("The language model returned an unexpected response.") from err


def complete(system: str, user: str) -> str:
    # Send one system and one user message, and return the model's text.
    base_url = config.get_secret("LLM_BASE_URL")
    api_key = config.get_secret("LLM_API_KEY")
    model = config.get_secret("LLM_MODEL")
    if not (base_url and api_key and model):
        raise LLMUnavailableError("The language model is not configured (LLM_BASE_URL, LLM_API_KEY, LLM_MODEL).")
    url = _endpoint(base_url)
    headers = {"Authorization": f"Bearer {api_key}"}
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0,
        "max_tokens": config.LLM_MAX_TOKENS,
    }
    problem = "no response"
    for attempt in range(1, config.LLM_RETRIES + 1):
        try:
            response = requests.post(url, json=body, headers=headers, timeout=config.LLM_TIMEOUT_SECONDS)
        except requests.exceptions.RequestException as err:
            problem = type(err).__name__
        else:
            status = response.status_code
            if status == 200:
                return _content(response)
            if status in (401, 403):
                raise LLMUnavailableError("The language model rejected the API key.")
            if status != 429 and status < 500:
                log.warning("LLM request failed: HTTP %s %s", status, response.text[:200])
                raise LLMUnavailableError(f"The language model rejected the request (HTTP {status}).")
            problem = f"HTTP {status}"
            log.warning("Temporary LLM failure: HTTP %s. Response: %s", status, response.text[:300])
        if attempt < config.LLM_RETRIES:
            delay = config.LLM_BACKOFF_SECONDS * (2 ** (attempt - 1))
            log.warning("Retrying LLM request in %.1f seconds (attempt %d/%d)", delay, attempt, config.LLM_RETRIES)
            time.sleep(delay)
    raise LLMUnavailableError(f"The language model could not be reached ({problem}).")

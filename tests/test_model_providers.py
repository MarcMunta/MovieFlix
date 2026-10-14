from __future__ import annotations

import json

import pytest
import requests

import model_providers
from model_providers import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    ModelClient,
    ModelConfig,
    ProviderError,
    default_config,
    validate_config,
)


class FakeResponse:
    def __init__(self, payload=None, status=200, headers=None):
        self.payload = payload
        self.status_code = status
        self.headers = headers or {}
        self.closed = False

    def iter_content(self, chunk_size):
        if isinstance(self.payload, Exception):
            yield b"not-json"
            return
        body = json.dumps(self.payload).encode("utf-8")
        for offset in range(0, len(body), chunk_size):
            yield body[offset : offset + chunk_size]

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.trust_env = True
        self.closed = False

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def close(self):
        self.closed = True


def client_with(monkeypatch, config, *responses):
    session = FakeSession(responses)
    monkeypatch.setattr(model_providers.requests, "Session", lambda: session)
    return ModelClient(config), session


def test_default_local_config_reads_existing_key_without_exposing_it(tmp_path, monkeypatch):
    secret = "fake-local-secret"
    path = tmp_path / "api-key"
    path.write_text(secret, encoding="utf-8")
    monkeypatch.setenv("MOVIEFLIX_MODE", "local")
    monkeypatch.delenv("RENDER", raising=False)

    config = default_config(path)

    assert config.base_url == DEFAULT_BASE_URL
    assert config.model == DEFAULT_MODEL
    assert config.api_key == secret
    assert secret not in repr(config)


@pytest.mark.parametrize(
    "url",
    [
        "http://models.example/v1",
        "ftp://127.0.0.1/models",
        "https://user:pass@example.test/v1",
        "https://example.test/v1?target=internal",
        "https://example.test/v1#fragment",
        "http://127.0.0.1:0/v1",
    ],
)
def test_invalid_or_unsafe_urls_are_rejected(url):
    config = ModelConfig("openai_compatible", url, "model", "fake-key")
    with pytest.raises(ValueError):
        validate_config(config)


def test_remote_https_requires_key_but_loopback_http_does_not():
    validate_config(ModelConfig("ollama", "http://[::1]:11434", "gemma", ""))
    with pytest.raises(ValueError, match="clave API"):
        validate_config(ModelConfig("anthropic", "https://api.anthropic.com/v1", "claude", ""))


def test_openai_compatible_request_shape_json_and_local_reasoning(monkeypatch):
    config = ModelConfig("openai_compatible", DEFAULT_BASE_URL, DEFAULT_MODEL, "fake-key")
    client, session = client_with(
        monkeypatch,
        config,
        FakeResponse({"choices": [{"message": {"content": '{"ok":true}'}}]}),
    )

    result = client.complete([{"role": "user", "content": "JSON"}], json_response=True)

    assert result == '{"ok":true}'
    method, url, request = session.calls[0]
    assert (method, url) == ("POST", DEFAULT_BASE_URL + "/chat/completions")
    assert request["json"]["response_format"] == {"type": "json_object"}
    assert request["json"]["reasoning_effort"] == "none"
    assert request["json"]["chat_template_kwargs"] == {
        "enable_thinking": False,
        "reasoning_effort": "none",
    }
    assert request["headers"]["Authorization"] == "Bearer fake-key"
    assert request["allow_redirects"] is False
    assert session.trust_env is False


def test_openai_remote_request_has_no_llamacpp_only_fields(monkeypatch):
    config = ModelConfig("openai_compatible", "https://models.example/v1", "own-model", "key")
    client, session = client_with(
        monkeypatch,
        config,
        FakeResponse({"choices": [{"message": {"content": "done"}}]}),
    )
    assert client.complete([{"role": "user", "content": "Hi"}]) == "done"
    payload = session.calls[0][2]["json"]
    assert "reasoning_effort" not in payload and "chat_template_kwargs" not in payload


def test_ollama_request_and_model_list(monkeypatch):
    config = ModelConfig("ollama", "http://localhost:11434", "qwen", "")
    client, session = client_with(
        monkeypatch,
        config,
        FakeResponse({"message": {"content": "{}"}}),
        FakeResponse({"models": [{"name": "qwen"}, {"model": "gemma"}]}),
    )

    assert client.complete([{"role": "user", "content": "data"}], json_response=True) == "{}"
    assert client.list_models() == ["qwen", "gemma"]
    request = session.calls[0][2]
    assert request["json"]["format"] == "json"
    assert request["json"]["stream"] is False
    assert session.calls[1][1] == "http://localhost:11434/api/tags"


def test_anthropic_request_and_response(monkeypatch):
    config = ModelConfig("anthropic", "https://api.anthropic.com/v1", "claude-test", "key")
    client, session = client_with(
        monkeypatch,
        config,
        FakeResponse({"content": [{"type": "text", "text": "answer"}]}),
        FakeResponse({"data": [{"id": "claude-test"}]}),
    )
    messages = [
        {"role": "system", "content": "Be concise"},
        {"role": "user", "content": "Question"},
    ]

    assert client.complete(messages) == "answer"
    assert client.list_models() == ["claude-test"]
    request = session.calls[0][2]
    assert request["headers"]["x-api-key"] == "key"
    assert request["headers"]["anthropic-version"] == "2023-06-01"
    assert request["json"]["system"] == "Be concise"
    assert request["json"]["messages"] == [{"role": "user", "content": "Question"}]


def test_gemini_request_json_mode_and_model_list(monkeypatch):
    config = ModelConfig(
        "gemini", "https://generativelanguage.googleapis.com/v1beta", "models/gemini-test", "key"
    )
    client, session = client_with(
        monkeypatch,
        config,
        FakeResponse({"candidates": [{"content": {"parts": [{"text": "{"}, {"text": "}"}]}}]}),
        FakeResponse({"models": [{"name": "models/gemini-test"}]}),
    )
    messages = [
        {"role": "developer", "content": "Return data"},
        {"role": "assistant", "content": "Earlier"},
        {"role": "user", "content": "Now"},
    ]

    assert client.complete(messages, json_response=True, max_tokens=50) == "{}"
    assert client.list_models() == ["gemini-test"]
    method, url, request = session.calls[0]
    assert method == "POST" and url.endswith("/models/gemini-test:generateContent")
    assert request["headers"]["x-goog-api-key"] == "key"
    assert request["json"]["generationConfig"] == {
        "maxOutputTokens": 50,
        "responseMimeType": "application/json",
    }
    assert request["json"]["contents"][0]["role"] == "model"


def test_timeout_and_http_errors_are_sanitized(monkeypatch):
    config = ModelConfig("openai_compatible", DEFAULT_BASE_URL, "model", "top-secret")
    client, _ = client_with(monkeypatch, config, requests.Timeout("top-secret in raw error"))
    with pytest.raises(ProviderError) as timeout:
        client.list_models()
    assert "top-secret" not in str(timeout.value)

    client, _ = client_with(monkeypatch, config, FakeResponse({"secret": "body"}, status=401))
    with pytest.raises(ProviderError) as http:
        client.list_models()
    assert str(http.value) == "El proveedor respondió con HTTP 401."


def test_redirect_and_malformed_response_fail_closed(monkeypatch):
    config = ModelConfig("openai_compatible", DEFAULT_BASE_URL, "model", "key")
    client, _ = client_with(monkeypatch, config, FakeResponse({}, status=302))
    with pytest.raises(ProviderError, match="redirección bloqueada"):
        client.list_models()

    client, _ = client_with(monkeypatch, config, FakeResponse(ValueError("bad json")))
    with pytest.raises(ProviderError, match="respuesta no válida"):
        client.list_models()

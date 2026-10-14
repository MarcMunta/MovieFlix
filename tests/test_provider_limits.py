from __future__ import annotations

import traceback

import pytest
import requests

import model_providers
from model_providers import MAX_RESPONSE_BYTES, ModelClient, ModelConfig, ProviderError


class TrackingResponse:
    def __init__(
        self,
        body: bytes,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        stream_error: Exception | None = None,
    ):
        self.body = body
        self.status_code = status
        self.headers = headers or {}
        self.stream_error = stream_error
        self.closed = False
        self.iterated = False

    def iter_content(self, chunk_size: int):
        self.iterated = True
        for offset in range(0, len(self.body), chunk_size):
            yield self.body[offset : offset + chunk_size]
        if self.stream_error is not None:
            raise self.stream_error

    def close(self) -> None:
        self.closed = True


class TrackingSession:
    def __init__(self, result: TrackingResponse | Exception):
        self.result = result
        self.trust_env = True
        self.closed = False
        self.calls: list[tuple[str, str, dict]] = []

    def request(self, method: str, url: str, **kwargs):
        self.calls.append((method, url, kwargs))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def close(self) -> None:
        self.closed = True


def make_client(monkeypatch, result: TrackingResponse | Exception):
    session = TrackingSession(result)
    monkeypatch.setattr(model_providers.requests, "Session", lambda: session)
    config = ModelConfig("openai_compatible", "http://127.0.0.1:8091/v1", "test-model", "fake-key")
    return ModelClient(config), session


def test_declared_oversized_response_is_rejected_before_read_and_closed(monkeypatch):
    response = TrackingResponse(b"{}", headers={"Content-Length": str(MAX_RESPONSE_BYTES + 1)})
    client, _ = make_client(monkeypatch, response)

    with pytest.raises(ProviderError, match="supera el límite permitido"):
        client._request("GET", "/models")

    assert response.iterated is False
    assert response.closed is True


def test_actual_response_size_is_bounded_when_content_length_is_absent(monkeypatch):
    valid_body = b"{}" + b" " * (MAX_RESPONSE_BYTES - 2)
    valid_response = TrackingResponse(valid_body)
    client, _ = make_client(monkeypatch, valid_response)

    assert client._request("GET", "/models") == {}
    assert valid_response.closed is True

    oversized_response = TrackingResponse(valid_body + b" ")
    client, _ = make_client(monkeypatch, oversized_response)
    with pytest.raises(ProviderError, match="supera el límite permitido"):
        client._request("GET", "/models")
    assert oversized_response.closed is True


def test_response_and_session_close_on_success_and_http_failure(monkeypatch):
    success = TrackingResponse(b"{}")
    client, session = make_client(monkeypatch, success)
    with client as entered:
        assert entered is client
        assert entered._request("GET", "/models") == {}
    assert success.closed is True
    assert session.closed is True

    failure = TrackingResponse(b'{"secret":"must-not-be-read"}', status=503)
    client, session = make_client(monkeypatch, failure)
    with pytest.raises(ProviderError, match="HTTP 503"):
        with client:
            client._request("GET", "/models")
    assert failure.iterated is False
    assert failure.closed is True
    assert session.closed is True


def test_request_exception_does_not_retain_secret_bearing_exception(monkeypatch):
    secret = "FAKE_TOKEN_SHOULD_NEVER_SURVIVE"
    raw_error = requests.ConnectionError(f"network failed Authorization: Bearer {secret}")
    client, session = make_client(monkeypatch, raw_error)

    with pytest.raises(ProviderError) as captured:
        with client:
            client._request("GET", "/models")

    error = captured.value
    rendered_traceback = "".join(
        traceback.format_exception(type(error), error, error.__traceback__)
    )
    assert secret not in str(error)
    assert secret not in rendered_traceback
    assert error.__cause__ is None
    assert error.__context__ is None
    assert session.closed is True


def test_stream_exception_is_sanitized_and_response_is_closed(monkeypatch):
    secret = "FAKE_STREAM_TOKEN_SHOULD_NEVER_SURVIVE"
    response = TrackingResponse(
        b'{"partial":',
        stream_error=requests.exceptions.ChunkedEncodingError(f"raw transport data {secret}"),
    )
    client, _ = make_client(monkeypatch, response)

    with pytest.raises(ProviderError) as captured:
        client._request("GET", "/models")

    error = captured.value
    rendered_traceback = "".join(
        traceback.format_exception(type(error), error, error.__traceback__)
    )
    assert str(error) == "No se pudo contactar con el proveedor."
    assert secret not in rendered_traceback
    assert error.__cause__ is None
    assert error.__context__ is None
    assert response.closed is True


def test_invalid_content_length_and_utf8_fail_without_metadata_leaks(monkeypatch):
    secret = "FAKE_HEADER_SECRET"
    response = TrackingResponse(b"{}", headers={"Content-Length": secret})
    client, _ = make_client(monkeypatch, response)
    with pytest.raises(ProviderError) as captured:
        client._request("GET", "/models")
    assert secret not in str(captured.value)
    assert response.closed is True

    response = TrackingResponse(b"\xff")
    client, _ = make_client(monkeypatch, response)
    with pytest.raises(ProviderError, match="respuesta no válida") as captured:
        client._request("GET", "/models")
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert response.closed is True

    secret = "FAKE_JSON_SECRET"
    response = TrackingResponse(f'{{"token":"{secret}"'.encode())
    client, _ = make_client(monkeypatch, response)
    with pytest.raises(ProviderError) as captured:
        client._request("GET", "/models")
    rendered_traceback = "".join(
        traceback.format_exception(
            type(captured.value), captured.value, captured.value.__traceback__
        )
    )
    assert secret not in rendered_traceback
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert response.closed is True


def test_excessive_json_nesting_is_sanitized(monkeypatch):
    response = TrackingResponse(b"[" * 1_100 + b"]" * 1_100)
    client, _ = make_client(monkeypatch, response)

    with pytest.raises(ProviderError, match="respuesta no válida") as captured:
        client._request("GET", "/models")

    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert response.closed is True


def test_streaming_preserves_request_security_options(monkeypatch):
    response = TrackingResponse(b"{}")
    client, session = make_client(monkeypatch, response)

    client._request("POST", "/chat/completions", payload={"model": "test-model"})

    _, _, request = session.calls[0]
    assert request["stream"] is True
    assert request["allow_redirects"] is False
    assert session.trust_env is False

"""Adaptadores HTTP mínimos para proveedores de modelos configurables."""

from __future__ import annotations

import ipaddress
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import requests

DEFAULT_BASE_URL = "http://127.0.0.1:8091/v1"
DEFAULT_MODEL = "ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF"
LOCAL_API_KEY_PATH = Path.home() / ".codex" / "local-models" / "api-key"
PROVIDERS = ("openai_compatible", "ollama", "anthropic", "gemini")
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_RESPONSE_CHUNK_BYTES = 64 * 1024


class ProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelConfig:
    provider: str
    base_url: str
    model: str
    api_key: str = field(repr=False)
    timeout: int = 90
    max_tokens: int = 1800
    server_managed: bool = False


def _is_loopback(hostname: str | None) -> bool:
    if not hostname:
        return False
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def is_loopback_url(url: str) -> bool:
    try:
        return _is_loopback(urlsplit(url).hostname)
    except ValueError:
        return False


def validate_config(config: ModelConfig) -> None:
    if config.provider not in PROVIDERS:
        raise ValueError("Proveedor no compatible.")
    if not config.model.strip() or len(config.model) > 300:
        raise ValueError("Indica un modelo válido.")
    if not isinstance(config.timeout, int) or isinstance(config.timeout, bool):
        raise ValueError("El tiempo de espera debe ser un entero.")
    if not 1 <= config.timeout <= 600:
        raise ValueError("El tiempo de espera debe estar entre 1 y 600 segundos.")
    if not isinstance(config.max_tokens, int) or isinstance(config.max_tokens, bool):
        raise ValueError("El máximo de tokens debe ser un entero.")
    if not 1 <= config.max_tokens <= 100_000:
        raise ValueError("El máximo de tokens debe estar entre 1 y 100.000.")

    try:
        parsed = urlsplit(config.base_url)
        port = parsed.port
    except ValueError as error:
        raise ValueError("La URL del proveedor no es válida.") from error
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("La URL debe usar HTTP o HTTPS e incluir un host.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("La URL no puede incluir credenciales, consulta ni fragmento.")
    if any(character.isspace() for character in config.base_url) or port == 0:
        raise ValueError("La URL del proveedor no es válida.")
    loopback = _is_loopback(parsed.hostname)
    if parsed.scheme == "http" and not loopback:
        raise ValueError("HTTP solo se permite para localhost o una IP de loopback.")
    if not loopback and not config.api_key:
        raise ValueError("Los proveedores remotos requieren una clave API.")


def _is_default_local(config: ModelConfig) -> bool:
    return (
        config.provider == "openai_compatible"
        and config.base_url.rstrip("/") == DEFAULT_BASE_URL
        and is_loopback_url(config.base_url)
    )


def default_config(api_key_path: Path | None = None) -> ModelConfig:
    key = ""
    local_mode = os.environ.get("MOVIEFLIX_MODE", "cloud") == "local"
    on_render = os.environ.get("RENDER", "").lower() == "true"
    if local_mode and not on_render:
        try:
            key = (api_key_path or LOCAL_API_KEY_PATH).read_text(encoding="utf-8").strip()
        except OSError:
            pass
    return ModelConfig("openai_compatible", DEFAULT_BASE_URL, DEFAULT_MODEL, key)


def _messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    if not isinstance(messages, list) or not messages:
        raise ValueError("Incluye al menos un mensaje.")
    clean = []
    for message in messages:
        if not isinstance(message, dict) or set(message) != {"role", "content"}:
            raise ValueError("Cada mensaje debe contener role y content.")
        role, content = message["role"], message["content"]
        if role not in {"system", "developer", "user", "assistant"}:
            raise ValueError("Rol de mensaje no compatible.")
        if not isinstance(content, str):
            raise ValueError("El contenido del mensaje debe ser texto.")
        clean.append({"role": role, "content": content})
    return clean


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(
            item["text"]
            for item in value
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        )
    return ""


class ModelClient:
    def __init__(self, config: ModelConfig):
        validate_config(config)
        self.config = config
        self._session = requests.Session()
        self._session.trust_env = False

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> ModelClient:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()

    def _request(self, method: str, path: str, *, payload: dict | None = None) -> dict:
        headers = {"Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if self.config.provider in {"openai_compatible", "ollama"} and self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        elif self.config.provider == "anthropic":
            headers["x-api-key"] = self.config.api_key
            headers["anthropic-version"] = "2023-06-01"
        elif self.config.provider == "gemini":
            headers["x-goog-api-key"] = self.config.api_key
        url = self.config.base_url.rstrip("/") + path
        request_error: str | None = None
        try:
            response = self._session.request(
                method,
                url,
                json=payload,
                headers=headers,
                timeout=self.config.timeout,
                allow_redirects=False,
                stream=True,
            )
        except requests.Timeout:
            request_error = "El proveedor agotó el tiempo de espera."
        except requests.RequestException:
            request_error = "No se pudo contactar con el proveedor."
        if request_error is not None:
            raise ProviderError(request_error) from None

        try:
            if 300 <= response.status_code < 400:
                raise ProviderError("El proveedor respondió con una redirección bloqueada.")
            if not 200 <= response.status_code < 300:
                raise ProviderError(f"El proveedor respondió con HTTP {response.status_code}.")

            content_length = response.headers.get("Content-Length")
            if content_length is not None:
                try:
                    declared_size = int(content_length, 10)
                except (TypeError, ValueError):
                    declared_size = -1
                if declared_size < 0:
                    raise ProviderError("El proveedor devolvió una respuesta no válida.")
                if declared_size > MAX_RESPONSE_BYTES:
                    raise ProviderError("La respuesta del proveedor supera el límite permitido.")

            body = bytearray()
            stream_error: str | None = None
            try:
                for chunk in response.iter_content(chunk_size=_RESPONSE_CHUNK_BYTES):
                    if not chunk:
                        continue
                    if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise ProviderError(
                            "La respuesta del proveedor supera el límite permitido."
                        )
                    body.extend(chunk)
            except requests.Timeout:
                stream_error = "El proveedor agotó el tiempo de espera."
            except requests.RequestException:
                stream_error = "No se pudo contactar con el proveedor."
            if stream_error is not None:
                raise ProviderError(stream_error) from None

            invalid_json = False
            try:
                data = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError, RecursionError):
                invalid_json = True
            if invalid_json or not isinstance(data, dict):
                raise ProviderError("El proveedor devolvió una respuesta no válida.") from None
            return data
        finally:
            response.close()

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        json_response: bool = False,
        max_tokens: int | None = None,
    ) -> str:
        clean = _messages(messages)
        limit = self.config.max_tokens if max_tokens is None else max_tokens
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100_000:
            raise ValueError("El máximo de tokens debe estar entre 1 y 100.000.")
        if self.config.provider == "openai_compatible":
            result = self._complete_openai(clean, limit, json_response)
        elif self.config.provider == "ollama":
            result = self._complete_ollama(clean, limit, json_response)
        elif self.config.provider == "anthropic":
            result = self._complete_anthropic(clean, limit)
        else:
            result = self._complete_gemini(clean, limit, json_response)
        if not result:
            raise ProviderError("El proveedor devolvió una respuesta vacía.")
        return result

    def _complete_openai(self, messages: list[dict[str, str]], limit: int, json_mode: bool) -> str:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "max_tokens": limit,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if _is_default_local(self.config):
            payload["chat_template_kwargs"] = {
                "enable_thinking": False,
                "reasoning_effort": "none",
            }
            payload["reasoning_effort"] = "none"
        elif self.config.base_url.rstrip(
            "/"
        ) == "https://api.groq.com/openai/v1" and self.config.model in {
            "openai/gpt-oss-120b",
            "openai/gpt-oss-20b",
        }:
            payload["reasoning_effort"] = "low"
        data = self._request("POST", "/chat/completions", payload=payload)
        try:
            return _text(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError):
            raise ProviderError("Respuesta OpenAI-compatible incompleta.") from None

    def _complete_ollama(self, messages: list[dict[str, str]], limit: int, json_mode: bool) -> str:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "stream": False,
            "options": {"num_predict": limit},
        }
        if json_mode:
            payload["format"] = "json"
        data = self._request("POST", "/api/chat", payload=payload)
        try:
            return _text(data["message"]["content"])
        except (KeyError, TypeError):
            raise ProviderError("Respuesta Ollama incompleta.") from None

    def _complete_anthropic(self, messages: list[dict[str, str]], limit: int) -> str:
        system = "\n\n".join(
            item["content"] for item in messages if item["role"] in {"system", "developer"}
        )
        conversation = [item for item in messages if item["role"] not in {"system", "developer"}]
        if not conversation:
            raise ValueError("Anthropic requiere al menos un mensaje de usuario o asistente.")
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": conversation,
            "max_tokens": limit,
        }
        if system:
            payload["system"] = system
        data = self._request("POST", "/messages", payload=payload)
        try:
            return _text(data["content"])
        except (KeyError, TypeError):
            raise ProviderError("Respuesta Anthropic incompleta.") from None

    def _complete_gemini(self, messages: list[dict[str, str]], limit: int, json_mode: bool) -> str:
        system = "\n\n".join(
            item["content"] for item in messages if item["role"] in {"system", "developer"}
        )
        contents = [
            {
                "role": "model" if item["role"] == "assistant" else "user",
                "parts": [{"text": item["content"]}],
            }
            for item in messages
            if item["role"] not in {"system", "developer"}
        ]
        if not contents:
            raise ValueError("Gemini requiere al menos un mensaje de usuario o asistente.")
        generation: dict[str, Any] = {"maxOutputTokens": limit}
        if json_mode:
            generation["responseMimeType"] = "application/json"
        payload: dict[str, Any] = {"contents": contents, "generationConfig": generation}
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        model = self.config.model.removeprefix("models/")
        data = self._request(
            "POST", f"/models/{quote(model, safe='')}:generateContent", payload=payload
        )
        try:
            return _text(data["candidates"][0]["content"]["parts"])
        except (KeyError, IndexError, TypeError):
            raise ProviderError("Respuesta Gemini incompleta o bloqueada.") from None

    def list_models(self) -> list[str]:
        paths = {
            "openai_compatible": "/models",
            "ollama": "/api/tags",
            "anthropic": "/models",
            "gemini": "/models",
        }
        data = self._request("GET", paths[self.config.provider])
        if self.config.provider in {"openai_compatible", "anthropic"}:
            items = data.get("data", [])
            names = [item.get("id") for item in items if isinstance(item, dict)]
        elif self.config.provider == "ollama":
            items = data.get("models", [])
            names = [
                item.get("name") or item.get("model") for item in items if isinstance(item, dict)
            ]
        else:
            items = data.get("models", [])
            names = [
                item.get("name", "").removeprefix("models/")
                for item in items
                if isinstance(item, dict)
            ]
        return list(dict.fromkeys(name for name in names if isinstance(name, str) and name))

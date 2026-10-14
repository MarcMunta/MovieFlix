"""Pantalla Streamlit y persistencia no secreta de la configuración de modelos."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import streamlit as st

from model_providers import (
    DEFAULT_BASE_URL,
    ModelClient,
    ModelConfig,
    ProviderError,
    default_config,
    is_loopback_url,
    validate_config,
)

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.environ.get("MOVIEFLIX_DATA_DIR", ROOT / "storage")) / "model-config.json"
PROVIDER_LABELS = {
    "openai_compatible": "OpenAI-compatible (llama.cpp, LM Studio, vLLM…)",
    "ollama": "Ollama nativo",
    "anthropic": "Anthropic Messages API",
    "gemini": "Google Gemini generateContent",
}
PUBLIC_API_BASE_URLS = {
    "openai_compatible": {
        "https://api.openai.com/v1",
        "https://openrouter.ai/api/v1",
        "https://api.groq.com/openai/v1",
        "https://api.together.xyz/v1",
    },
    "anthropic": {"https://api.anthropic.com/v1"},
    "gemini": {"https://generativelanguage.googleapis.com/v1beta"},
    "ollama": set(),
}


def _local_settings() -> bool:
    return (
        os.environ.get("MOVIEFLIX_MODE", "cloud") == "local"
        and os.environ.get("RENDER", "").lower() != "true"
    )


def _validate_destination(config: ModelConfig) -> None:
    validate_config(config)
    if (
        not _local_settings()
        and config.base_url.rstrip("/") not in PUBLIC_API_BASE_URLS[config.provider]
    ):
        raise ValueError(
            "En la demo pública usa una de las URLs API indicadas. "
            "Los servidores locales y endpoints personalizados se configuran al ejecutar la app en tu equipo."
        )


def _without_secret(config: ModelConfig) -> dict[str, str | int]:
    return {
        "provider": config.provider,
        "base_url": config.base_url,
        "model": config.model,
        "timeout": config.timeout,
        "max_tokens": config.max_tokens,
    }


def _persist_config(config: ModelConfig) -> None:
    """Escritura atómica a ruta fija; la clave API nunca llega al disco."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=CONFIG_PATH.parent, delete=False, suffix=".tmp"
        ) as file:
            temporary = Path(file.name)
            json.dump(_without_secret(config), file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, CONFIG_PATH)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _load_persisted_config() -> ModelConfig | None:
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        config = ModelConfig(
            provider=str(data["provider"]),
            base_url=str(data["base_url"]),
            model=str(data["model"]),
            api_key="",
            timeout=int(data.get("timeout", 90)),
            max_tokens=int(data.get("max_tokens", 1800)),
        )
        validation_config = config
        if not is_loopback_url(config.base_url):
            validation_config = ModelConfig(
                config.provider,
                config.base_url,
                config.model,
                "required-in-session",
                config.timeout,
                config.max_tokens,
            )
        validate_config(validation_config)
    except (OSError, KeyError, TypeError, ValueError):
        return None
    if config.provider == "openai_compatible" and config.base_url.rstrip("/") == DEFAULT_BASE_URL:
        local = default_config()
        config = ModelConfig(
            config.provider,
            config.base_url,
            config.model,
            local.api_key,
            config.timeout,
            config.max_tokens,
        )
    return config


def get_model_config() -> ModelConfig:
    current = st.session_state.get("model_config")
    if isinstance(current, ModelConfig):
        try:
            validate_config(current)
        except ValueError:
            st.session_state.pop("model_config", None)
        else:
            return current
    persisted = _load_persisted_config()
    if persisted is not None:
        return persisted
    return default_config()


def _configuration_access() -> tuple[bool, str]:
    if _local_settings():
        return True, "Configuración local editable."
    return (
        True,
        "Configuración solo para esta sesión; claves y preferencias no se guardan en Render.",
    )


def _candidate(
    current: ModelConfig,
    provider: str,
    base_url: str,
    model: str,
    api_key: str,
    timeout: int,
    max_tokens: int,
) -> ModelConfig:
    clean_url = base_url.strip().rstrip("/")
    same_destination = provider == current.provider and clean_url == current.base_url.rstrip("/")
    key = api_key.strip() or (current.api_key if same_destination else "")
    return ModelConfig(provider, clean_url, model.strip(), key, int(timeout), int(max_tokens))


def render_model_settings() -> None:
    current = get_model_config()
    can_edit, access_note = _configuration_access()
    st.title("Configuración del modelo")
    st.write("Conecta un servidor local o una API propia mediante uno de estos protocolos.")
    st.caption(
        "OpenAI-compatible: /chat/completions · Ollama: /api/chat · "
        "Anthropic: /messages · Gemini: generateContent"
    )
    if not _local_settings():
        st.info(
            "En Render conecta tu propia API pública. El localhost de tu ordenador solo funciona "
            "cuando ejecutas MovieFlix en ese ordenador. La clave permanece en tu sesión."
        )
        st.write(
            "URLs admitidas en Render: "
            + ", ".join(sorted(url for urls in PUBLIC_API_BASE_URLS.values() for url in urls))
        )
    st.info(f"Activo: {PROVIDER_LABELS[current.provider]} · {current.model} · {current.base_url}")
    if not can_edit:
        st.warning("La configuración pública solo puede cambiarla el administrador. " + access_note)

    provider_names = list(PROVIDER_LABELS)
    with st.form("model_settings"):
        provider = st.selectbox(
            "Protocolo",
            provider_names,
            index=provider_names.index(current.provider),
            format_func=PROVIDER_LABELS.get,
            disabled=not can_edit,
        )
        base_url = st.text_input("URL base", value=current.base_url, disabled=not can_edit)
        model = st.text_input("Modelo", value=current.model, disabled=not can_edit)
        api_key = st.text_input(
            "Clave API (opcional en local)",
            type="password",
            value="",
            placeholder="Se conserva solo durante esta sesión",
            disabled=not can_edit,
        )
        timeout = st.number_input(
            "Tiempo de espera (segundos)",
            min_value=1,
            max_value=600,
            value=current.timeout,
            disabled=not can_edit,
        )
        max_tokens = st.number_input(
            "Máximo de tokens de salida",
            min_value=1,
            max_value=100_000,
            value=current.max_tokens,
            disabled=not can_edit,
        )
        test, save = st.columns(2)
        test_connection = test.form_submit_button("Probar conexión", disabled=not can_edit)
        save_config = save.form_submit_button("Guardar configuración", disabled=not can_edit)

    if not (test_connection or save_config):
        return
    if not can_edit:
        st.error("No tienes permiso para cambiar o probar esta configuración.")
        return
    try:
        candidate = _candidate(
            current, provider, base_url, model, api_key, int(timeout), int(max_tokens)
        )
        _validate_destination(candidate)
        with ModelClient(candidate) as client:
            models = client.list_models()
        if not models:
            raise ProviderError("El proveedor no devolvió ningún modelo disponible.")
    except (ValueError, ProviderError) as error:
        st.error(str(error))
        return

    preview = ", ".join(models[:8])
    suffix = "…" if len(models) > 8 else ""
    st.success(f"Conexión correcta. Modelos detectados: {preview}{suffix}")
    if save_config:
        st.session_state["model_config"] = candidate
        if _local_settings():
            try:
                _persist_config(candidate)
            except OSError:
                st.warning(
                    "Configuración activa en esta sesión; no se pudieron guardar las preferencias en disco."
                )
        if candidate.model not in models:
            st.warning("Guardado, pero el modelo indicado no aparece en la lista del proveedor.")
        else:
            st.success("Configuración activa. La clave permanece solo en esta sesión.")

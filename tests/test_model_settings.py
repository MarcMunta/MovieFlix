from __future__ import annotations

import json

import pytest

import model_providers
import model_settings
from model_providers import DEFAULT_BASE_URL, ModelClient, ModelConfig


@pytest.fixture(autouse=True)
def no_real_server_credentials(monkeypatch):
    for name in model_settings.SERVER_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_persistence_excludes_api_key_and_roundtrips_preferences(tmp_path, monkeypatch):
    path = tmp_path / "storage" / "model-config.json"
    monkeypatch.setattr(model_settings, "CONFIG_PATH", path)
    config = ModelConfig(
        "anthropic", "https://api.anthropic.com/v1", "claude-test", "do-not-persist", 45, 900
    )

    model_settings._persist_config(config)

    raw = path.read_text(encoding="utf-8")
    assert "do-not-persist" not in raw
    assert "api_key" not in json.loads(raw)
    loaded = model_settings._load_persisted_config()
    assert loaded == ModelConfig(
        "anthropic", "https://api.anthropic.com/v1", "claude-test", "", 45, 900
    )


def test_get_config_precedence_session_then_disk_then_local_default(tmp_path, monkeypatch):
    monkeypatch.setattr(model_settings, "CONFIG_PATH", tmp_path / "model-config.json")
    monkeypatch.setattr(model_settings.st, "session_state", {})
    key_path = tmp_path / "api-key"
    key_path.write_text("local-key", encoding="utf-8")
    monkeypatch.setattr(model_providers, "LOCAL_API_KEY_PATH", key_path)
    monkeypatch.setenv("MOVIEFLIX_MODE", "local")
    monkeypatch.delenv("RENDER", raising=False)

    fallback = model_settings.get_model_config()
    assert fallback.base_url == DEFAULT_BASE_URL and fallback.api_key == "local-key"

    persisted = ModelConfig("ollama", "http://localhost:11434", "gemma", "not-saved")
    model_settings._persist_config(persisted)
    assert model_settings.get_model_config().api_key == ""
    session = ModelConfig("ollama", "http://localhost:11434", "gemma", "session-key")
    model_settings.st.session_state["model_config"] = session
    assert model_settings.get_model_config() is session


def test_corrupt_or_unsafe_disk_config_is_ignored(tmp_path, monkeypatch):
    path = tmp_path / "model-config.json"
    monkeypatch.setattr(model_settings, "CONFIG_PATH", path)
    path.write_text(
        json.dumps(
            {
                "provider": "openai_compatible",
                "base_url": "http://metadata.internal/v1",
                "model": "bad",
            }
        ),
        encoding="utf-8",
    )
    assert model_settings._load_persisted_config() is None


def test_destination_change_never_forwards_existing_key():
    current = ModelConfig("openai_compatible", DEFAULT_BASE_URL, "local", "local-secret")
    changed = model_settings._candidate(
        current, "openai_compatible", "https://models.example/v1", "remote", "", 90, 1000
    )
    unchanged = model_settings._candidate(
        current, "openai_compatible", DEFAULT_BASE_URL, "local", "", 90, 1000
    )
    assert changed.api_key == ""
    assert unchanged.api_key == "local-secret"


def test_configuration_access_local_or_session_only_cloud(monkeypatch):
    monkeypatch.setenv("MOVIEFLIX_MODE", "local")
    monkeypatch.delenv("RENDER", raising=False)
    allowed, note = model_settings._configuration_access()
    assert allowed
    assert "local editable" in note

    monkeypatch.setenv("MOVIEFLIX_MODE", "cloud")
    monkeypatch.setenv("RENDER", "true")
    allowed, note = model_settings._configuration_access()
    assert allowed
    assert "solo para esta sesión" in note
    assert "no se guardan" in note


@pytest.mark.parametrize(
    "base_url",
    [
        "http://127.0.0.1:8091/v1",
        "https://10.0.0.1/v1",
        "https://models.example/v1",
    ],
    ids=["loopback", "private-address", "custom-https"],
)
def test_cloud_rejects_unapproved_model_destinations(monkeypatch, base_url):
    monkeypatch.setenv("MOVIEFLIX_MODE", "cloud")
    monkeypatch.setenv("RENDER", "true")
    config = ModelConfig("openai_compatible", base_url, "test-model", "fake-test-key")

    with pytest.raises(ValueError, match="demo pública"):
        model_settings._validate_destination(config)


@pytest.mark.parametrize(
    ("provider", "base_url"),
    [
        (provider, base_url)
        for provider, urls in model_settings.PUBLIC_API_BASE_URLS.items()
        for base_url in sorted(urls)
    ],
)
def test_approved_remote_destinations_require_session_key(monkeypatch, provider, base_url):
    monkeypatch.setenv("MOVIEFLIX_MODE", "cloud")
    monkeypatch.setenv("RENDER", "true")
    config = ModelConfig(provider, base_url, "test-model", "")

    with pytest.raises(ValueError, match="requieren una clave API"):
        model_settings._validate_destination(config)


def test_render_never_counts_as_local_settings_even_when_mode_is_local(monkeypatch):
    monkeypatch.setenv("MOVIEFLIX_MODE", "local")
    monkeypatch.setenv("RENDER", "true")

    assert model_settings._local_settings() is False


@pytest.mark.parametrize(
    "config",
    [
        ModelConfig("openai_compatible", "http://127.0.0.1:9000/v1", "local-model", ""),
        ModelConfig(
            "openai_compatible",
            "https://models.example/v1",
            "remote-model",
            "fake-test-key",
        ),
    ],
    ids=["custom-loopback", "custom-https"],
)
def test_local_mode_allows_valid_custom_destinations(monkeypatch, config):
    monkeypatch.setenv("MOVIEFLIX_MODE", "local")
    monkeypatch.delenv("RENDER", raising=False)

    model_settings._validate_destination(config)


def test_cloud_server_default_is_fixed_private_and_not_persisted(monkeypatch):
    private_key = "fake-server-private-key"
    monkeypatch.setenv("MOVIEFLIX_MODE", "cloud")
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("MOVIEFLIX_LLM_API_KEY", private_key)

    config = model_settings.server_default_config()

    assert config == ModelConfig(
        "openai_compatible",
        "https://api.groq.com/openai/v1",
        "openai/gpt-oss-120b",
        private_key,
        90,
        2048,
        server_managed=True,
    )
    assert private_key not in repr(config)
    persisted = model_settings._without_secret(config)
    assert "api_key" not in persisted and "server_managed" not in persisted


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("MOVIEFLIX_LLM_MODEL", "unapproved/model", "lista gratuita autorizada"),
        ("MOVIEFLIX_LLM_BASE_URL", "https://models.example/v1", "solo admite"),
        ("MOVIEFLIX_LLM_PROVIDER", "anthropic", "solo admite"),
    ],
)
def test_server_default_rejects_unapproved_source_or_model(monkeypatch, name, value, message):
    monkeypatch.setenv("MOVIEFLIX_MODE", "cloud")
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("MOVIEFLIX_LLM_API_KEY", "fake-server-key")
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=message):
        model_settings.server_default_config()


def test_server_default_rejects_incomplete_environment(monkeypatch):
    monkeypatch.setenv("MOVIEFLIX_MODE", "cloud")
    monkeypatch.setenv("MOVIEFLIX_LLM_MODEL", "openai/gpt-oss-20b")

    with pytest.raises(ValueError, match="MOVIEFLIX_LLM_API_KEY"):
        model_settings.server_default_config()


def test_cloud_config_precedence_session_owner_key_over_server(monkeypatch):
    monkeypatch.setenv("MOVIEFLIX_MODE", "cloud")
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("MOVIEFLIX_LLM_API_KEY", "fake-server-key")
    own = ModelConfig("anthropic", "https://api.anthropic.com/v1", "claude-own", "fake-own-key")
    monkeypatch.setattr(model_settings.st, "session_state", {"model_config": own})

    assert model_settings.get_model_config() is own

    model_settings.st.session_state.clear()
    assert model_settings.get_model_config().server_managed


def test_server_key_cannot_be_inherited_by_personal_override(monkeypatch):
    monkeypatch.setenv("MOVIEFLIX_MODE", "cloud")
    monkeypatch.setenv("RENDER", "true")
    current = ModelConfig(
        "openai_compatible",
        model_settings.SERVER_BASE_URL,
        model_settings.SERVER_DEFAULT_MODEL,
        "fake-owner-key",
        90,
        2048,
        server_managed=True,
    )

    changed = model_settings._candidate(
        current,
        "openai_compatible",
        model_settings.SERVER_BASE_URL,
        "openai/gpt-oss-20b",
        "",
        90,
        2048,
    )

    assert changed.api_key == "" and not changed.server_managed
    with pytest.raises(ValueError, match="requieren una clave API"):
        model_settings._validate_destination(changed)


def test_demo_restore_clears_only_model_widgets_and_keeps_chats(monkeypatch):
    state = {
        "model_config": "custom",
        "model_api_key": "fake-own-key",
        "model_name": "custom-model",
        "ai_messages": [{"role": "user", "content": "keep"}],
        "guided_messages": [{"role": "assistant", "content": "keep"}],
        "unrelated": 1,
    }
    monkeypatch.setattr(model_settings.st, "session_state", state)

    model_settings._clear_session_model_config()

    assert "model_config" not in state and "model_api_key" not in state
    assert state["ai_messages"] and state["guided_messages"] and state["unrelated"] == 1


def test_groq_gpt_oss_uses_documented_low_reasoning_effort(monkeypatch):
    config = ModelConfig(
        "openai_compatible",
        model_settings.SERVER_BASE_URL,
        "openai/gpt-oss-120b",
        "fake-key",
    )
    captured = {}
    client = ModelClient(config)

    def fake_request(method, path, *, payload=None):
        captured.update(method=method, path=path, payload=payload)
        return {"choices": [{"message": {"content": "answer"}}]}

    monkeypatch.setattr(client, "_request", fake_request)
    try:
        assert client.complete([{"role": "user", "content": "question"}]) == "answer"
    finally:
        client.close()

    assert captured["payload"]["reasoning_effort"] == "low"

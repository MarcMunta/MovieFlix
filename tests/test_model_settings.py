from __future__ import annotations

import json

import model_providers
import model_settings
from model_providers import DEFAULT_BASE_URL, ModelConfig


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


def test_configuration_access_local_or_authenticated_cloud(monkeypatch):
    monkeypatch.setattr(model_settings.st, "session_state", {"edit_password": "typed-password"})
    monkeypatch.setenv("MOVIEFLIX_MODE", "local")
    monkeypatch.delenv("RENDER", raising=False)
    assert model_settings._configuration_access()[0]

    seen = []
    monkeypatch.setenv("MOVIEFLIX_MODE", "cloud")
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setattr(
        model_settings,
        "write_access",
        lambda password: seen.append(password) or (password == "typed-password", "status"),
    )
    allowed, _ = model_settings._configuration_access()
    assert allowed and seen == ["typed-password"]

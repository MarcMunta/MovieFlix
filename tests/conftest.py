import pytest


@pytest.fixture(autouse=True)
def local_mode(monkeypatch):
    monkeypatch.setenv("MOVIEFLIX_MODE", "local")

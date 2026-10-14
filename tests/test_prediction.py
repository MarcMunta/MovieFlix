"""Contract and real-artifact tests for isolated model inference."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime

import pytest

import prediction
from prediction import PredictionError, PredictionInputError, run_predictions

PAYLOAD = {
    "plot": "A spaceship crew explores a distant planet and fights an alien threat.",
    "year": 2020,
    "runtime": 110,
}


def fake_result() -> dict:
    return {
        "decision_tree": {
            "prediction": "Drama",
            "ranking": [
                {"Género": "Drama", "Probabilidad": 0.75},
                {"Género": "Comedy", "Probabilidad": 0.25},
            ],
        },
        "random_forest": {
            "prediction": "Comedy",
            "ranking": [
                {"Género": "Comedy", "Probabilidad": 0.6},
                {"Género": "Drama", "Probabilidad": 0.4},
            ],
        },
    }


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {"plot": PAYLOAD["plot"], "year": 2020},
        PAYLOAD | {"model_path": "C:/untrusted/modelo.joblib"},
        PAYLOAD | {"model": "../../otro-modelo"},
        PAYLOAD | {"plot": "muy corta"},
        PAYLOAD | {"plot": "x" * 5001},
        PAYLOAD | {"year": True},
        PAYLOAD | {"year": 1799},
        PAYLOAD | {"year": datetime.now(UTC).year + 6},
        PAYLOAD | {"runtime": 0},
        PAYLOAD | {"runtime": 90.5},
    ],
    ids=[
        "not-a-dict",
        "missing-field",
        "arbitrary-path",
        "arbitrary-model",
        "short-plot",
        "long-plot",
        "boolean-year",
        "old-year",
        "future-year",
        "zero-runtime",
        "non-integer-runtime",
    ],
)
def test_invalid_payload_is_rejected_before_starting_worker(monkeypatch, payload):
    def unexpected_run(*args, **kwargs):
        raise AssertionError("invalid input must not start the model worker")

    monkeypatch.setattr(prediction.subprocess, "run", unexpected_run)

    with pytest.raises(PredictionInputError):
        run_predictions(payload)


def test_parent_uses_fixed_worker_bounded_contract_and_transient_thread_limits(monkeypatch):
    calls = []
    encoded = json.dumps(
        {"ok": True, "result": fake_result()}, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout=encoded, stderr=b"")

    monkeypatch.setenv("OMP_NUM_THREADS", "9")
    monkeypatch.setattr(prediction.subprocess, "run", fake_run)

    assert run_predictions(PAYLOAD) == fake_result()
    assert len(calls) == 1
    command, options = calls[0]
    assert command == [sys.executable, str(prediction.WORKER_PATH), "--worker"]
    assert options["cwd"] == prediction.ROOT
    assert options["timeout"] == 120
    assert options["check"] is False
    assert options["capture_output"] is True
    assert json.loads(options["input"].decode("utf-8")) == PAYLOAD
    assert options["env"]["OMP_NUM_THREADS"] == "1"
    assert options["env"]["OPENBLAS_NUM_THREADS"] == "1"
    assert prediction.os.environ["OMP_NUM_THREADS"] == "9"


def test_worker_failure_does_not_expose_stderr(monkeypatch):
    secret_diagnostic = "private native library path and secret"

    def failed_run(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            1,
            stdout=b'{"ok":false,"error":"prediction_failed"}',
            stderr=secret_diagnostic.encode(),
        )

    monkeypatch.setattr(prediction.subprocess, "run", failed_run)

    with pytest.raises(PredictionError) as error:
        run_predictions(PAYLOAD)

    assert secret_diagnostic not in str(error.value)
    assert str(prediction.MODEL_PATH) not in str(error.value)


def test_busy_worker_fails_after_bounded_lock_wait_without_starting_process(monkeypatch):
    class BusyLock:
        def acquire(self, *, timeout):
            assert timeout == 10
            return False

        def release(self):
            raise AssertionError("an unacquired lock must not be released")

    monkeypatch.setattr(prediction, "_WORKER_LOCK", BusyLock())
    monkeypatch.setattr(
        prediction.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("busy predictor must not start another worker"),
    )

    with pytest.raises(PredictionError, match="ocupado"):
        run_predictions(PAYLOAD)


def test_timeout_is_reported_without_waiting_or_leaking_command(monkeypatch):
    def timed_out(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"], stderr=b"private diagnostic")

    monkeypatch.setattr(prediction.subprocess, "run", timed_out)

    with pytest.raises(PredictionError, match="agotó el tiempo") as error:
        run_predictions(PAYLOAD)

    assert "private diagnostic" not in str(error.value)
    assert str(prediction.WORKER_PATH) not in str(error.value)


def test_actual_worker_returns_both_model_rankings_from_owned_artifact():
    result = run_predictions(PAYLOAD)

    assert set(result) == {"decision_tree", "random_forest"}
    assert result["decision_tree"]["prediction"] == "Documentary"
    assert result["decision_tree"]["ranking"][0] == {
        "Género": "Documentary",
        "Probabilidad": 1.0,
    }
    assert result["random_forest"]["prediction"] == "Documentary"
    assert result["random_forest"]["ranking"][0]["Género"] == "Documentary"
    assert result["random_forest"]["ranking"][0]["Probabilidad"] == pytest.approx(0.248495677122318)
    for model_result in result.values():
        assert len(model_result["ranking"]) == 5
        probabilities = [row["Probabilidad"] for row in model_result["ranking"]]
        assert probabilities == sorted(probabilities, reverse=True)

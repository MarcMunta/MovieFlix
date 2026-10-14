"""Predicción aislada en un proceso hijo para mantener ligera la aplicación web."""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
WORKER_PATH = ROOT / "prediction.py"
MODEL_PATH = ROOT / "modelo.joblib"
ALGORITHMS = ("decision_tree", "random_forest")
LOCK_WAIT_SECONDS = 10
PROCESS_TIMEOUT_SECONDS = 120
MAX_REQUEST_BYTES = 16_384
MAX_RESPONSE_BYTES = 65_536


class PredictionError(RuntimeError):
    """La predicción no pudo ejecutarse de forma segura."""


class PredictionInputError(PredictionError, ValueError):
    """Los campos de entrada no cumplen el contrato del predictor."""


_WORKER_LOCK = threading.Lock()


def _validate_payload(payload: object) -> dict[str, str | int]:
    if not isinstance(payload, dict) or set(payload) != {"plot", "year", "runtime"}:
        raise PredictionInputError("Incluye únicamente sinopsis, año y duración.")
    plot = payload["plot"]
    if not isinstance(plot, str) or not 15 <= len(plot.strip()) <= 5000:
        raise PredictionInputError("La sinopsis debe tener entre 15 y 5.000 caracteres.")
    year = payload["year"]
    if isinstance(year, bool) or not isinstance(year, int):
        raise PredictionInputError("El año debe ser un entero.")
    if not 1800 <= year <= datetime.now(UTC).year + 5:
        raise PredictionInputError("El año está fuera del intervalo permitido.")
    runtime = payload["runtime"]
    if isinstance(runtime, bool) or not isinstance(runtime, int):
        raise PredictionInputError("La duración debe ser un entero.")
    if not 1 <= runtime <= 2000:
        raise PredictionInputError("La duración debe estar entre 1 y 2.000 minutos.")
    return {"plot": plot.strip(), "year": year, "runtime": runtime}


def _worker_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "BLIS_NUM_THREADS",
        "LOKY_MAX_CPU_COUNT",
    ):
        environment[name] = "1"
    return environment


def _validate_result(value: object) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict) or set(value) != set(ALGORITHMS):
        raise PredictionError("El predictor devolvió un resultado no válido.")
    clean: dict[str, dict[str, Any]] = {}
    for algorithm in ALGORITHMS:
        item = value[algorithm]
        if not isinstance(item, dict) or set(item) != {"prediction", "ranking"}:
            raise PredictionError("El predictor devolvió un resultado no válido.")
        predicted = item["prediction"]
        ranking = item["ranking"]
        if not isinstance(predicted, str) or not 1 <= len(predicted) <= 200:
            raise PredictionError("El predictor devolvió un resultado no válido.")
        if not isinstance(ranking, list) or not 1 <= len(ranking) <= 5:
            raise PredictionError("El predictor devolvió un resultado no válido.")
        clean_ranking = []
        previous = math.inf
        for row in ranking:
            if not isinstance(row, dict) or set(row) != {"Género", "Probabilidad"}:
                raise PredictionError("El predictor devolvió un resultado no válido.")
            genre = row["Género"]
            probability = row["Probabilidad"]
            if (
                not isinstance(genre, str)
                or not 1 <= len(genre) <= 200
                or isinstance(probability, bool)
                or not isinstance(probability, (int, float))
                or not math.isfinite(probability)
                or not 0 <= probability <= 1
                or probability > previous
            ):
                raise PredictionError("El predictor devolvió un resultado no válido.")
            previous = float(probability)
            clean_ranking.append({"Género": genre, "Probabilidad": float(probability)})
        clean[algorithm] = {"prediction": predicted, "ranking": clean_ranking}
    return clean


def run_predictions(payload: object) -> dict[str, dict[str, Any]]:
    """Ejecuta ambos modelos en un único worker con ruta, tiempo y concurrencia fijos."""
    request = json.dumps(_validate_payload(payload), ensure_ascii=False, separators=(",", ":"))
    request_bytes = request.encode("utf-8")
    if len(request_bytes) > MAX_REQUEST_BYTES:
        raise PredictionInputError("La entrada de predicción supera el límite permitido.")
    if not _WORKER_LOCK.acquire(timeout=LOCK_WAIT_SECONDS):
        raise PredictionError("El predictor está ocupado. Inténtalo de nuevo en unos segundos.")
    try:
        try:
            completed = subprocess.run(
                [sys.executable, str(WORKER_PATH), "--worker"],
                input=request_bytes,
                capture_output=True,
                cwd=ROOT,
                env=_worker_environment(),
                timeout=PROCESS_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise PredictionError("La predicción agotó el tiempo disponible.") from None
        except OSError:
            raise PredictionError("No se pudo iniciar el predictor.") from None
    finally:
        _WORKER_LOCK.release()
    if completed.returncode != 0 or not 1 <= len(completed.stdout) <= MAX_RESPONSE_BYTES:
        raise PredictionError("No se pudo generar la predicción.")
    try:
        response = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise PredictionError("El predictor devolvió un resultado no válido.") from None
    if not isinstance(response, dict) or response.get("ok") is not True:
        raise PredictionError("No se pudo generar la predicción.")
    return _validate_result(response.get("result"))


def _predict(payload: dict[str, str | int]) -> dict[str, dict[str, Any]]:
    # Imports pesados solo dentro del proceso hijo; la app web no carga sklearn para su health check.
    import joblib
    import pandas as pd

    artifact = joblib.load(MODEL_PATH, mmap_mode="r")
    if not isinstance(artifact, dict) or not {*ALGORITHMS, "metadata"} <= artifact.keys():
        raise PredictionError("Artefacto de modelo no válido.")
    inputs = pd.DataFrame([payload], columns=["plot", "year", "runtime"])
    result: dict[str, dict[str, Any]] = {}
    for algorithm in ALGORITHMS:
        model = artifact[algorithm]
        probabilities = model.predict_proba(inputs)[0]
        classes = model.classes_
        if len(classes) != len(probabilities):
            raise PredictionError("Artefacto de modelo no válido.")
        ranking = sorted(
            (
                (str(genre), float(probability))
                for genre, probability in zip(classes, probabilities, strict=True)
            ),
            key=lambda item: item[1],
            reverse=True,
        )[:5]
        result[algorithm] = {
            "prediction": str(model.predict(inputs)[0]),
            "ranking": [
                {"Género": genre, "Probabilidad": probability}
                for genre, probability in ranking
            ],
        }
    return _validate_result(result)


def _worker_main() -> int:
    try:
        raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if not 1 <= len(raw) <= MAX_REQUEST_BYTES:
            raise PredictionInputError("Entrada no válida.")
        payload = json.loads(raw.decode("utf-8"))
        result = _predict(_validate_payload(payload))
        response = {"ok": True, "result": result}
        output = json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(output) > MAX_RESPONSE_BYTES:
            raise PredictionError("Resultado demasiado grande.")
        sys.stdout.buffer.write(output)
        return 0
    except PredictionInputError:
        sys.stdout.write('{"ok":false,"error":"invalid_input"}')
        return 2
    except (PredictionError, OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        sys.stdout.write('{"ok":false,"error":"prediction_failed"}')
        return 1


def main() -> int:
    if sys.argv[1:] != ["--worker"]:
        return 2
    return _worker_main()


if __name__ == "__main__":
    raise SystemExit(main())

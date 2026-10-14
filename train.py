"""Árbol y Random Forest: primer género registrado, desde sinopsis, año y duración."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import joblib
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.impute import SimpleImputer
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline
from sklearn.tree import DecisionTreeClassifier

from dataset import CATALOG_PATH, ROOT, movie_key, normalize, read_catalog

FEATURES = ["plot", "year", "runtime"]


def training_data(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    work["target"] = work["genres"].str.split(";").str[0].str.strip()
    work = work[work["plot"].str.strip().ne("") & work["target"].ne("")].copy()
    # Remove exact repeated plots BEFORE splitting; group duplicate title/year editions.
    work["plot_key"] = work["plot"].map(normalize)
    work = work.drop_duplicates("plot_key")
    counts = work["target"].value_counts()
    work = work[work["target"].isin(counts[counts >= 40].index)].copy()
    work["group"] = [movie_key(t, int(y)) for t, y in zip(work.title, work.year, strict=True)]
    return work.reset_index(drop=True)


def build_pipeline(model) -> Pipeline:
    return Pipeline(
        [
            (
                "features",
                ColumnTransformer(
                    [
                        (
                            "text",
                            TfidfVectorizer(
                                max_features=3500,
                                ngram_range=(1, 2),
                                min_df=3,
                                stop_words="english",
                                sublinear_tf=True,
                            ),
                            "plot",
                        ),
                        ("numbers", SimpleImputer(strategy="median"), ["year", "runtime"]),
                    ]
                ),
            ),
            ("model", model),
        ]
    )


def train(catalog: Path, output: Path, trees: int = 160, include_additions: bool = False) -> dict:
    raw = read_catalog(catalog)
    if include_additions:
        from store import MovieStore, combined_catalog

        raw = combined_catalog(raw, MovieStore())
    work = training_data(raw)
    if len(work) < 200:
        raise ValueError("No hay suficientes sinopsis etiquetadas para entrenar y evaluar.")
    split = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
    development_idx, validation_idx = next(split.split(work, groups=work["group"]))
    development = work.iloc[development_idx]
    reserve = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=73)
    train_idx, test_idx = next(reserve.split(development, groups=development["group"]))
    train_rows, test_rows = development.iloc[train_idx], development.iloc[test_idx]
    validation_rows = work.iloc[validation_idx]
    assert set(train_rows.group).isdisjoint(test_rows.group)
    assert set(validation_rows.group).isdisjoint(set(train_rows.group) | set(test_rows.group))
    if set(work.target) != set(train_rows.target):
        raise ValueError("El split dejó clases sin entrenamiento; revisar el dataset.")
    models = {
        "decision_tree": build_pipeline(
            DecisionTreeClassifier(
                max_depth=50,
                min_samples_leaf=2,
                random_state=42,
            )
        ),
        "random_forest": build_pipeline(
            RandomForestClassifier(
                n_estimators=trees,
                max_depth=80,
                max_features="sqrt",
                min_samples_leaf=1,
                bootstrap=True,
                oob_score=True,
                n_jobs=2,
                random_state=42,
            )
        ),
        "baseline": build_pipeline(DummyClassifier(strategy="most_frequent")),
    }
    labels = sorted(work.target.unique())
    scores = {}
    for name, model in models.items():
        print(f"Entrenando {name} ({len(train_rows)} filas)...", flush=True)
        model.fit(train_rows[FEATURES], train_rows.target)
        prediction = model.predict(test_rows[FEATURES])
        scores[name] = {
            "accuracy": float(accuracy_score(test_rows.target, prediction)),
            "macro_f1": float(
                f1_score(
                    test_rows.target, prediction, labels=labels, average="macro", zero_division=0
                )
            ),
            "report": classification_report(
                test_rows.target, prediction, labels=labels, output_dict=True, zero_division=0
            ),
            "confusion_matrix": confusion_matrix(
                test_rows.target, prediction, labels=labels
            ).tolist(),
        }
    forest = models["random_forest"]["model"]
    forest.n_jobs = 1  # Small serving footprint on Render.
    metadata = {
        "task": "Clasificar el primer género registrado (no todos los géneros)",
        "features": FEATURES,
        "classes": labels,
        "catalog_rows": len(raw),
        "eligible_rows": len(work),
        "train_rows": len(train_rows),
        "test_rows": len(test_rows),
        "validation_rows": len(validation_rows),
        "excluded_rows": len(raw) - len(work),
        "random_state": 42,
        "split": "60/20/20 train/validación/test agrupado por título/año; sinopsis deduplicadas",
        "evaluation_note": "El 20% inicial diagnosticó subajuste. Test final reservado dentro del 80% restante, sin usarlo para elegir parámetros.",
        "group_overlap": 0,
        "preprocessing_fit": "solo train",
        "trees": trees,
        "class_distribution": {k: int(v) for k, v in work.target.value_counts().items()},
        "metrics": scores,
        "oob_accuracy": float(forest.oob_score_),
        "sklearn_version": sklearn.__version__,
        "catalog_sha256": hashlib.sha256(catalog.read_bytes()).hexdigest(),
        "included_additions": include_additions,
        "limitations": [
            "El orden de géneros del dataset no es una etiqueta editorial de género principal.",
            "Sinopsis mayoritariamente en inglés; predicción en español sin validación específica.",
            "Las probabilidades no están calibradas y no garantizan acierto.",
            "OOB comparte el vocabulario ajustado en train: test agrupado es la evaluación principal.",
            "Altas visibles al instante; modelo actualizado solo al ejecutar train.py otra vez.",
        ],
    }
    artifact = {
        "decision_tree": models["decision_tree"],
        "random_forest": models["random_forest"],
        "metadata": metadata,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp")
    joblib.dump(artifact, temporary, compress=3)
    os.replace(temporary, output)
    (ROOT / "metrics.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {k: {m: v[m] for m in ("accuracy", "macro_f1")} for k, v in scores.items()}, indent=2
        )
    )
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    parser.add_argument("--output", type=Path, default=ROOT / "modelo.joblib")
    parser.add_argument("--trees", type=int, default=160)
    parser.add_argument(
        "--include-additions", action="store_true", help="Incluir altas manuales validadas"
    )
    args = parser.parse_args()
    if not 10 <= args.trees <= 500:
        parser.error("--trees debe estar entre 10 y 500")
    train(args.catalog, args.output, args.trees, args.include_additions)


if __name__ == "__main__":
    main()

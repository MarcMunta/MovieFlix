"""Descarga reproducible, extrae solo películas y crea el catálogo de la app."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import urllib.request
import zipfile
from pathlib import Path

from dataset import ROOT, prepare

SLUG = "manaswinsripatnala/movie-flix-dataset"
URL = f"https://www.kaggle.com/api/v1/datasets/download/{SLUG}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="Descargar si falta el original")
    args = parser.parse_args()
    raw = ROOT / "data" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    archive = raw / "movie-flix-dataset.zip"
    movies = raw / "mflix.movies.csv"
    if args.download and not archive.exists():
        partial = archive.with_suffix(".part")
        try:
            req = urllib.request.Request(URL, headers={"User-Agent": "MovieFlix-coursework/1.0"})
            with urllib.request.urlopen(req, timeout=120) as src, partial.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            if not zipfile.is_zipfile(partial):
                raise ValueError(
                    "Kaggle no devolvió un ZIP válido; comprueba el acceso al dataset."
                )
            partial.replace(archive)
        finally:
            partial.unlink(missing_ok=True)
    if not movies.exists() and archive.exists():
        with zipfile.ZipFile(archive) as z:
            member = next(
                item for item in z.infolist() if Path(item.filename).name == "mflix.movies.csv"
            )
            if member.file_size > 150_000_000:
                raise ValueError("El CSV excede el tamaño esperado.")
            with z.open(member) as src, movies.open("wb") as dst:
                shutil.copyfileobj(src, dst)
    if not movies.exists():
        raise FileNotFoundError("Falta el CSV original. Ejecuta prepare_data.py --download.")
    info = prepare(movies)
    info.update(
        {
            "dataset": SLUG,
            "source_url": f"https://www.kaggle.com/datasets/{SLUG}",
            "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest()
            if archive.exists()
            else None,
            "license_reported_by_kaggle": "MIT",
            "download_date": "2026-10-14",
            "excluded": ["users", "sessions", "comments", "theaters", "embedded_movies"],
        }
    )
    (ROOT / "data" / "provenance.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(info, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

"""Catálogo público normalizado; sin usuarios, sesiones ni comentarios personales."""

from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
CATALOG_PATH = ROOT / "data" / "movies.csv"
COLUMNS = [
    "id",
    "title",
    "year",
    "runtime",
    "genres",
    "plot",
    "directors",
    "cast",
    "countries",
    "languages",
    "imdb_rating",
    "imdb_votes",
    "type",
    "source",
    "manual_rating",
]
NUMERIC = ["year", "runtime", "imdb_rating", "imdb_votes", "manual_rating"]


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text).casefold())
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).split())


def movie_key(title: str, year: int) -> str:
    return f"{normalize(title)}|{year}"


def read_catalog(path: Path = CATALOG_PATH) -> pd.DataFrame:
    frame = pd.read_csv(path, keep_default_na=False, dtype=str)
    if set(COLUMNS) - set(frame.columns):
        raise ValueError("El catálogo no tiene las columnas esperadas. Ejecuta prepare_data.py.")
    for column in NUMERIC:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame[COLUMNS]


def prepare(raw_path: Path, output: Path = CATALOG_PATH) -> dict:
    frame = pd.read_csv(raw_path, keep_default_na=False, dtype=str)
    result = pd.DataFrame(index=frame.index)
    result["id"] = frame["_id"]
    result["title"] = frame["title"]
    for key in ("year", "runtime", "type"):
        result[key] = frame[key]
    # Some years are strings such as "1981–". Keep their first four-digit year.
    result["year"] = result["year"].str.extract(r"(\d{4})", expand=False)
    result["plot"] = frame["plot"].where(frame["plot"].str.strip().ne(""), frame["fullplot"])
    for field in ("genres", "directors", "cast", "countries", "languages"):
        indexed = sorted(
            (col for col in frame if re.fullmatch(rf"{field}\[\d+\]", col)),
            key=lambda col: int(re.search(r"\d+", col).group()),
        )
        result[field] = frame[indexed].apply(
            lambda row: "; ".join(dict.fromkeys(v.strip() for v in row if v.strip())),
            axis=1,
        )
    result["imdb_rating"] = frame["imdb.rating"]
    result["imdb_votes"] = frame["imdb.votes"]
    result["source"] = "Kaggle: movie-flix"
    result["manual_rating"] = ""
    before = len(result)
    result = result.drop_duplicates("id")
    output.parent.mkdir(parents=True, exist_ok=True)
    result[COLUMNS].to_csv(output, index=False)
    return {
        "raw_rows": before,
        "catalog_rows": len(result),
        "removed_duplicate_ids": before - len(result),
        "raw_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
        "catalog_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "columns": COLUMNS,
    }


def export_csv(frame: pd.DataFrame) -> bytes:
    """Neutraliza fórmulas al abrir el CSV en una hoja de cálculo."""
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(COLUMNS)
    for row in frame[COLUMNS].itertuples(index=False, name=None):
        safe = []
        for value in row:
            text = "" if pd.isna(value) else str(value)
            if text.lstrip().startswith(("=", "+", "-", "@")):
                text = "'" + text
            safe.append(text)
        writer.writerow(safe)
    return stream.getvalue().encode("utf-8-sig")

"""Altas transaccionales separadas del CSV original; unicidad y validación estricta."""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from dataset import COLUMNS, ROOT, movie_key


@dataclass(frozen=True)
class Movie:
    title: str
    year: int
    runtime: int
    genres: str
    plot: str
    directors: str = ""
    cast: str = ""
    countries: str = ""
    languages: str = ""
    imdb_rating: float | None = None


def validate_movie(values: dict, allowed_genres: set[str]) -> Movie:
    accepted = set(Movie.__dataclass_fields__)
    if set(values) - accepted:
        raise ValueError("Campos desconocidos: " + ", ".join(sorted(set(values) - accepted)))
    required = {"title", "year", "runtime", "genres", "plot"}
    if required - set(values):
        raise ValueError("Faltan campos: " + ", ".join(sorted(required - set(values))))
    clean = dict(values)
    for field in ("title", "genres", "plot", "directors", "cast", "countries", "languages"):
        value = clean.get(field, "")
        if not isinstance(value, str):
            raise ValueError(f"{field} debe ser texto.")
        clean[field] = value.strip()
        if any(ord(c) < 32 and c not in "\n\t" for c in clean[field]):
            raise ValueError(f"{field} contiene caracteres de control.")
    if not 1 <= len(clean["title"]) <= 200:
        raise ValueError("El título debe tener entre 1 y 200 caracteres.")
    if not 15 <= len(clean["plot"]) <= 5000:
        raise ValueError("La sinopsis debe tener entre 15 y 5.000 caracteres.")
    for field in ("directors", "cast", "countries", "languages"):
        if len(clean[field]) > 1000:
            raise ValueError(f"{field} supera 1.000 caracteres.")
    for field, low, high in (
        ("year", 1800, datetime.now(UTC).year + 5),
        ("runtime", 1, 2000),
    ):
        value = clean[field]
        if isinstance(value, bool):
            raise ValueError(f"{field} debe ser un entero.")
        try:
            integer = int(value)
        except (ValueError, TypeError, OverflowError) as error:
            raise ValueError(f"{field} debe ser un entero.") from error
        if isinstance(value, float) and value != integer:
            raise ValueError(f"{field} debe ser un entero.")
        if not low <= integer <= high:
            raise ValueError(f"{field} debe estar entre {low} y {high}.")
        clean[field] = integer
    genres = list(dict.fromkeys(v.strip() for v in clean["genres"].split(";") if v.strip()))
    if not genres or len(genres) > 3 or set(genres) - allowed_genres:
        raise ValueError("Elige entre 1 y 3 géneros del catálogo.")
    clean["genres"] = "; ".join(genres)
    if clean.get("imdb_rating") in (None, ""):
        clean["imdb_rating"] = None
    else:
        try:
            rating = float(clean["imdb_rating"])
        except (ValueError, TypeError) as error:
            raise ValueError("La valoración debe ser numérica.") from error
        if not 0 <= rating <= 10 or isinstance(clean["imdb_rating"], bool):
            raise ValueError("La valoración debe estar entre 0 y 10.")
        clean["imdb_rating"] = rating
    return Movie(**clean)


def storage_path() -> Path:
    return Path(os.environ.get("MOVIEFLIX_DATA_DIR", ROOT / "storage")) / "additions.sqlite3"


def write_access(password: str = "") -> tuple[bool, str]:
    """En la nube: disco persistente y contraseña obligatorios, nunca escritura anónima."""
    mode = os.environ.get("MOVIEFLIX_MODE", "cloud")
    on_render = os.environ.get("RENDER", "").lower() == "true"
    if mode == "local" and not on_render:
        return True, "Las altas se guardan en este equipo."
    if mode not in {"local", "cloud"}:
        return False, "MOVIEFLIX_MODE debe ser local o cloud."
    path = storage_path().resolve()
    if not path.is_relative_to(Path("/var/data").resolve()):
        return False, "Render gratuito: consulta disponible. Guardar requiere disco persistente."
    expected = os.environ.get("MOVIEFLIX_ADMIN_PASSWORD", "")
    if not expected:
        return False, "Configura MOVIEFLIX_ADMIN_PASSWORD en Render para habilitar las altas."
    if not secrets.compare_digest(password.encode(), expected.encode()):
        return False, "Introduce la contraseña de edición para guardar nuevas películas."
    return True, "Las altas se guardan en el disco persistente de Render."


class MovieStore:
    def __init__(self, path: Path | None = None):
        self.path = path or storage_path()

    @contextmanager
    def connection(self, read_only: bool = False):
        if read_only:
            db = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
        else:
            db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def read(self) -> pd.DataFrame:
        if not self.path.exists():
            return pd.DataFrame(columns=COLUMNS)
        with self.connection(read_only=True) as db:
            rows = db.execute("SELECT payload FROM additions ORDER BY created_at, id").fetchall()
        return pd.DataFrame([json.loads(row[0]) for row in rows], columns=COLUMNS)

    def add(self, values: dict, base: pd.DataFrame, password: str = "") -> str:
        allowed, reason = write_access(password)
        if not allowed:
            raise PermissionError(reason)
        genres = set(base["genres"].str.split("; ").explode().dropna()) - {""}
        movie = validate_movie(values, genres)
        key = movie_key(movie.title, movie.year)
        if any(movie_key(t, int(y)) == key for t, y in zip(base.title, base.year, strict=True)):
            raise ValueError("Ya existe una película con ese título y año.")
        identifier = "local-" + str(uuid.uuid4())
        record = asdict(movie) | {
            "id": identifier,
            "imdb_votes": None,
            "type": "movie",
            "source": "Alta manual (sin verificación externa)",
            "manual_rating": movie.imdb_rating,
            "imdb_rating": None,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.connection() as db:
                db.execute("""CREATE TABLE IF NOT EXISTS additions (
                    id TEXT PRIMARY KEY, movie_key TEXT NOT NULL UNIQUE,
                    payload TEXT NOT NULL, created_at TEXT NOT NULL)""")
                db.execute(
                    "INSERT INTO additions (id, movie_key, payload, created_at) VALUES (?, ?, ?, ?)",
                    (
                        identifier,
                        key,
                        json.dumps(record, ensure_ascii=False),
                        datetime.now(UTC).isoformat(),
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError("Ya existe una película con ese título y año.") from error
        return identifier


def combined_catalog(base: pd.DataFrame, store: MovieStore) -> pd.DataFrame:
    additions = store.read()
    if additions.empty:
        return base.copy()
    return pd.concat([base, additions], ignore_index=True)

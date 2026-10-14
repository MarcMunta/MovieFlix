"""Consultas del LLM a una copia aislada del catálogo, con permisos de solo lectura."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass

import pandas as pd

from dataset import COLUMNS, normalize


class QueryError(ValueError):
    """Consulta rechazada, inválida o fuera de presupuesto."""


@dataclass(frozen=True)
class QueryResult:
    sql: str
    columns: list[str]
    rows: list[tuple]
    truncated: bool


class CatalogQueries:
    """Cada conversación opera sobre un snapshot; nunca abre archivos de la máquina."""

    FUNCTIONS = {
        "abs",
        "avg",
        "count",
        "sum",
        "total",
        "min",
        "max",
        "round",
        "coalesce",
        "ifnull",
        "nullif",
        "length",
        "lower",
        "upper",
        "trim",
        "ltrim",
        "rtrim",
        "instr",
        "substr",
        "substring",
        "replace",
        "like",
        "glob",
        "group_concat",
        "typeof",
        "date",
        "strftime",
        "julianday",
        "printf",
        "format",
        "iif",
        "if",
        "row_number",
        "rank",
        "dense_rank",
        "percent_rank",
        "cume_dist",
        "ntile",
        "lag",
        "lead",
        "first_value",
        "last_value",
        "nth_value",
        "contains_tag",
        "json_valid",
        "json_extract",
        "json_array_length",
    }

    def __init__(self, frame: pd.DataFrame, *, timeout_seconds: float = 2, max_rows: int = 50):
        if timeout_seconds <= 0 or not 1 <= max_rows <= 200:
            raise ValueError("Presupuesto de consultas inválido.")
        self.timeout_seconds = timeout_seconds
        self.max_rows = max_rows
        self.db = sqlite3.connect(":memory:", cached_statements=0)
        self.reads_movies = False
        snapshot = frame[COLUMNS].copy()
        snapshot.insert(0, "catalog_order", range(1, len(snapshot) + 1))
        snapshot.to_sql("movies", self.db, index=False)
        self.db.execute("CREATE INDEX movies_id ON movies(id)")
        self.db.execute("CREATE INDEX movies_title ON movies(title)")
        self.db.execute("CREATE INDEX movies_year ON movies(year)")
        self.db.create_function("contains_tag", 2, self._contains_tag, deterministic=True)
        self.db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 500_000)
        self.db.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, 64)
        self.db.setlimit(sqlite3.SQLITE_LIMIT_COMPOUND_SELECT, 10)
        self.db.setlimit(sqlite3.SQLITE_LIMIT_EXPR_DEPTH, 50)
        self.db.setlimit(sqlite3.SQLITE_LIMIT_VDBE_OP, 100_000)
        self.db.execute("PRAGMA query_only=ON")
        self.db.set_authorizer(self._authorize)

    @staticmethod
    def _contains_tag(value: str | None, tag: str | None) -> int:
        if not value or not tag:
            return 0
        return int(normalize(tag or "") in {normalize(v) for v in (value or "").split(";")})

    def _authorize(
        self,
        action: int,
        arg1: str | None,
        arg2: str | None,
        database: str | None,
        trigger: str | None,
    ) -> int:
        if action in {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE}:
            return sqlite3.SQLITE_OK
        if (
            action == sqlite3.SQLITE_READ
            and arg1 == "movies"
            and (database == "main" or (database is None and arg2 == ""))
        ):
            self.reads_movies = True
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() in self.FUNCTIONS:
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    def execute(self, sql: str) -> QueryResult:
        if not isinstance(sql, str) or not 1 <= len(sql.strip()) <= 10000:
            raise QueryError("La consulta debe contener entre 1 y 10.000 caracteres.")
        deadline = time.monotonic() + self.timeout_seconds
        self.reads_movies = False
        self.db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        try:
            cursor = self.db.execute(sql)
            if cursor.description is None:
                raise QueryError("Solo se permiten consultas de lectura.")
            columns = [column[0] for column in cursor.description]
            rows = []
            result_bytes = 0
            for row in cursor:
                result_bytes += sum(len(str(value).encode("utf-8")) for value in row)
                if result_bytes > 1_000_000:
                    raise QueryError(
                        "El resultado excede el presupuesto. Selecciona menos columnas o filas."
                    )
                rows.append(row)
                if len(rows) > self.max_rows:
                    break
            cursor.close()
            return QueryResult(sql, columns, rows[: self.max_rows], len(rows) > self.max_rows)
        except sqlite3.Error as error:
            # SQLite error strings contain schema diagnostics, never provider credentials.
            raise QueryError(f"Consulta no ejecutada: {error}") from None
        finally:
            self.db.set_progress_handler(None, 0)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> CatalogQueries:
        return self

    def __exit__(self, *_) -> None:
        self.close()

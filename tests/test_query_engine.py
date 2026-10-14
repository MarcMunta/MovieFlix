"""Security and integration coverage for the read-only catalogue SQL engine."""

from __future__ import annotations

import time
from dataclasses import is_dataclass

import pandas as pd
import pytest

from dataset import COLUMNS
from query_engine import CatalogQueries, QueryError, QueryResult


@pytest.fixture
def catalog() -> pd.DataFrame:
    def movie(**overrides: object) -> dict[str, object]:
        record: dict[str, object] = {
            "id": "",
            "title": "",
            "year": 2000,
            "runtime": 100,
            "genres": "Drama",
            "plot": "Public test plot.",
            "directors": "Test Director",
            "cast": "Test Performer",
            "countries": "Spain",
            "languages": "Spanish",
            "imdb_rating": 7.0,
            "imdb_votes": 1000,
            "type": "movie",
            "source": "fixture",
            "manual_rating": None,
        }
        record.update(overrides)
        return record

    # Physical order is deliberately unrelated to chronological order.
    records = [
        movie(
            id="input-first", title="First Input", year=2005, genres="Adventure", imdb_rating=8.5
        ),
        movie(id="musical", title="Only Musical", year=1986, genres="Musical", imdb_rating=None),
        movie(id="oldest", title="Oldest Film", year=1942, imdb_rating=float("nan")),
        movie(
            id="comedy-a", title="Comedy One", year=1999, genres="Comedy; Drama", imdb_rating=7.5
        ),
        movie(id="newest", title="Newest Film", year=2024, genres="Fantasy", imdb_rating=6.0),
        movie(id="science", title="Science Film", year=2012, genres="Sci-Fi", imdb_rating=8.0),
        movie(id="comedy-b", title="Comedy Two", year=2018, genres="comedy", imdb_rating=9.0),
        movie(
            id="action", title="Action Film", year=2001, genres="Action; Thriller", imdb_rating=5.0
        ),
    ]
    return pd.DataFrame(records, columns=COLUMNS)


def test_query_result_shape_and_public_movie_columns(catalog):
    sql = "SELECT * FROM movies ORDER BY catalog_order"

    with CatalogQueries(catalog) as queries:
        result = queries.execute(sql)

    assert isinstance(result, QueryResult)
    assert is_dataclass(result)
    assert result.sql == sql
    assert len(result.columns) == len(COLUMNS) + 1
    assert set(result.columns) == {*COLUMNS, "catalog_order"}
    assert len(result.rows) == len(catalog)
    assert result.rows[0][result.columns.index("id")] == "input-first"
    assert result.truncated is False


def test_catalog_order_is_physical_order_not_year_order(catalog):
    with CatalogQueries(catalog) as queries:
        physical = queries.execute(
            "SELECT id, catalog_order FROM movies ORDER BY catalog_order LIMIT 1"
        )
        chronological = queries.execute(
            "SELECT id, catalog_order FROM movies ORDER BY year, catalog_order LIMIT 1"
        )

    assert physical.rows == [("input-first", 1)]
    assert chronological.rows == [("oldest", 3)]


def test_aggregates_ignore_none_and_nan(catalog):
    sql = """
        SELECT COUNT(*) AS total, COUNT(imdb_rating) AS rated, AVG(imdb_rating) AS average
        FROM movies
        WHERE id IN ('input-first', 'musical', 'oldest')
    """

    with CatalogQueries(catalog) as queries:
        all_rows = queries.execute("SELECT COUNT(*) AS total FROM movies")
        result = queries.execute(sql)

    assert all_rows.rows == [(len(catalog),)]
    assert result.columns == ["total", "rated", "average"]
    assert result.rows[0][0:2] == (3, 1)
    assert result.rows[0][2] == pytest.approx(8.5)


def test_contains_tag_is_exact_and_case_insensitive(catalog):
    with CatalogQueries(catalog) as queries:
        result = queries.execute(
            "SELECT id FROM movies WHERE contains_tag(genres, 'COMEDY') ORDER BY catalog_order"
        )

    assert result.rows == [("comedy-a",), ("comedy-b",)]
    assert ("musical",) not in result.rows


def test_ctes_joins_and_window_functions_are_supported(catalog):
    sql = """
        WITH ranked AS (
            SELECT id, title, ROW_NUMBER() OVER (ORDER BY year, catalog_order) AS position
            FROM movies
        ), paired AS (
            SELECT ranked.title, movies.id, ranked.position
            FROM ranked
            JOIN movies ON movies.id = ranked.id
        )
        SELECT title, id, position FROM paired ORDER BY position LIMIT 3
    """

    with CatalogQueries(catalog) as queries:
        result = queries.execute(sql)

    assert result.columns == ["title", "id", "position"]
    assert result.rows == [
        ("Oldest Film", "oldest", 1),
        ("Only Musical", "musical", 2),
        ("Comedy One", "comedy-a", 3),
    ]


def test_common_text_and_date_functions_are_supported(catalog):
    with CatalogQueries(catalog) as queries:
        result = queries.execute(
            "SELECT UPPER(title), LENGTH(title), DATE('2000-01-02', '+1 day') "
            "FROM movies WHERE id = 'input-first'"
        )

    assert result.rows == [("FIRST INPUT", len("First Input"), "2000-01-03")]


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO movies (id) VALUES ('owned')",
        "UPDATE movies SET title = 'owned'",
        "DELETE FROM movies",
        "DROP TABLE movies",
        "CREATE TABLE secrets (value TEXT)",
        "ATTACH DATABASE ':memory:' AS attached",
        "PRAGMA table_info(movies)",
        "SELECT name FROM sqlite_master",
        "SELECT load_extension('untrusted-extension')",
        "SELECT readfile('untrusted-file')",
        "SELECT writefile('untrusted-file', 'owned')",
        "SELECT COUNT(*) FROM movies; SELECT 2",
        "WITH replacement(value) AS (VALUES ('owned')) "
        "UPDATE movies SET title = (SELECT value FROM replacement)",
    ],
)
def test_forbidden_sql_is_rejected_without_mutating_catalog(catalog, sql):
    before = catalog.copy(deep=True)

    with CatalogQueries(catalog) as queries:
        with pytest.raises(QueryError):
            queries.execute(sql)
        remaining = queries.execute("SELECT id FROM movies ORDER BY catalog_order")

    assert remaining.rows == [(movie_id,) for movie_id in catalog["id"]]
    pd.testing.assert_frame_equal(catalog, before)


def test_semicolon_and_sql_keywords_inside_literal_are_allowed(catalog):
    text = "DELETE; DROP TABLE movies; still plain text"

    with CatalogQueries(catalog) as queries:
        result = queries.execute("SELECT 'DELETE; DROP TABLE movies; still plain text' AS note")

    assert result.rows == [(text,)]
    assert result.columns == ["note"]


def test_row_cap_marks_truncation_and_does_not_mutate_input(catalog):
    before = catalog.copy(deep=True)
    sql = """
        SELECT a.id, b.id, c.id
        FROM movies AS a
        CROSS JOIN movies AS b
        CROSS JOIN movies AS c
        ORDER BY a.catalog_order, b.catalog_order, c.catalog_order
    """

    with CatalogQueries(catalog, max_rows=50) as queries:
        result = queries.execute(sql)
        remaining = queries.execute("SELECT id FROM movies ORDER BY catalog_order")

    assert len(result.rows) == 50
    assert result.truncated is True
    assert remaining.rows == [(movie_id,) for movie_id in catalog["id"]]
    assert remaining.truncated is False
    pd.testing.assert_frame_equal(catalog, before)


def test_progress_budget_interrupts_expensive_recursive_cte(catalog):
    sql = """
        WITH RECURSIVE sequence(value) AS (
            VALUES (1)
            UNION ALL
            SELECT value + 1 FROM sequence WHERE value < 5000000
        )
        SELECT SUM(value) FROM sequence
    """
    started = time.monotonic()

    with CatalogQueries(catalog, timeout_seconds=0.02) as queries:
        with pytest.raises(QueryError):
            queries.execute(sql)

    assert time.monotonic() - started < 2.0


def test_unknown_field_and_oversized_query_raise_query_error(catalog):
    with CatalogQueries(catalog) as queries:
        with pytest.raises(QueryError):
            queries.execute("SELECT private_notes FROM movies")
        with pytest.raises(QueryError):
            queries.execute("SELECT '" + ("x" * 10001) + "'")


def test_sql_input_cannot_execute_python_or_leak_environment(catalog, monkeypatch, tmp_path):
    secret = "fake-secret-that-must-not-leak"
    marker = tmp_path / "must-not-exist.txt"
    monkeypatch.setenv("MOVIEFLIX_QUERY_TEST_SECRET", secret)
    before = catalog.copy(deep=True)
    payload = (
        "SELECT __import__('os').system('echo owned > " + str(marker).replace("\\", "/") + "')"
    )

    with CatalogQueries(catalog) as queries:
        with pytest.raises(QueryError) as error:
            queries.execute(payload)

    assert secret not in str(error.value)
    assert not marker.exists()
    pd.testing.assert_frame_equal(catalog, before)

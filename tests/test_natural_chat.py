"""Regression tests for deterministic, natural Spanish catalogue questions."""

from __future__ import annotations

import pandas as pd
import pytest

from assistant import respond
from dataset import COLUMNS


@pytest.fixture
def natural_catalog() -> pd.DataFrame:
    def movie(**overrides: object) -> dict[str, object]:
        record: dict[str, object] = {
            "id": "",
            "title": "",
            "year": 2000,
            "runtime": 100,
            "genres": "Drama",
            "plot": "Sinopsis de prueba.",
            "directors": "Dirección de prueba",
            "cast": "Intérprete de prueba",
            "countries": "España",
            "languages": "Spanish",
            "imdb_rating": 7.0,
            "imdb_votes": 2000,
            "type": "movie",
            "source": "fixture",
            "manual_rating": None,
        }
        record.update(overrides)
        return record

    records = [
        movie(
            id="row-first",
            title="La Isla Azul",
            year=2005,
            genres="Adventure",
            plot="Una cartógrafa descubre una isla que cambia de lugar.",
            directors="Marta Soler",
        ),
        movie(
            id="row-second",
            title="Top Gun",
            year=1986,
            genres="Action; Drama",
            plot="Aviadores compiten en una escuela de élite.",
            directors="Tony Scott",
            imdb_rating=6.9,
            imdb_votes=5000,
        ),
        movie(
            id="row-oldest",
            title="El Faro Antiguo",
            year=1942,
            plot="Una guardiana protege la luz durante una tormenta.",
            directors="Inés Vidal",
        ),
        movie(
            id="row-1999",
            title="Un Verano Distinto",
            year=1999,
            genres="Comedy",
            plot="Dos hermanas restauran el cine de su pueblo.",
            directors="Pablo León",
        ),
        movie(
            id="row-newest",
            title="Bosque de Cristal",
            year=2024,
            genres="Fantasy",
            plot="Un niño devuelve la voz a un bosque encantado.",
            directors="Álvaro Casas",
        ),
        movie(
            id="row-last",
            title="Horizonte Rojo",
            year=2012,
            genres="Sci-Fi",
            plot="Una ingeniera intenta salvar una colonia marciana.",
            directors="Lucía Romero",
        ),
    ]
    return pd.DataFrame(records, columns=COLUMNS)


def assert_ids(reply: object, expected: list[str]) -> None:
    assert len(reply.rows) == len(expected)
    assert reply.rows["id"].tolist() == expected
    assert reply.context_ids == expected


def test_polite_greeting_prefix_keeps_dataset_order_intent(natural_catalog):
    reply = respond("Hola, dime la primera pelicula de todo tu dataset", natural_catalog)

    assert_ids(reply, ["row-first"])
    assert "La Isla Azul" in reply.text


def test_greeting_alone_does_not_return_catalog_rows(natural_catalog):
    reply = respond("Hola, buenos días, ¿qué tal?", natural_catalog)

    assert reply.text.strip()
    assert reply.rows.empty
    assert reply.context_ids == []


@pytest.mark.parametrize(
    ("message", "expected_id"),
    [
        ("Enséñame el primer registro del dataset", "row-first"),
        ("¿Cuál es la película más antigua?", "row-oldest"),
        ("Muéstrame el último registro del dataset", "row-last"),
        ("¿Cuál es la película más nueva?", "row-newest"),
    ],
)
def test_physical_position_and_year_extremes_are_distinct(natural_catalog, message, expected_id):
    reply = respond(message, natural_catalog)

    assert_ids(reply, [expected_id])


def test_first_n_and_second_record_preserve_physical_order(natural_catalog):
    first_two = respond("Dime las primeras 2 películas del dataset", natural_catalog)
    second = respond("Ahora muéstrame el segundo registro", natural_catalog)

    assert_ids(first_two, ["row-first", "row-second"])
    assert_ids(second, ["row-second"])


@pytest.mark.parametrize(
    ("message", "field", "expected"),
    [
        ("¿Quién dirige La Isla Azul?", "directors", "Marta Soler"),
        (
            "Dime la sinopsis de La Isla Azul",
            "plot",
            "Una cartógrafa descubre una isla que cambia de lugar.",
        ),
        ("¿De qué año es La Isla Azul?", "year", 2005),
    ],
)
def test_explicit_unquoted_title_returns_requested_field(natural_catalog, message, field, expected):
    reply = respond(message, natural_catalog)

    assert_ids(reply, ["row-first"])
    assert reply.rows.iloc[0][field] == expected
    assert str(expected) in reply.text


def test_quoted_top_gun_is_a_title_search_not_a_ranking(natural_catalog):
    reply = respond('Háblame de "Top Gun"', natural_catalog)

    assert_ids(reply, ["row-second"])
    assert reply.rows.iloc[0].title == "Top Gun"


def test_followup_uses_the_single_previous_result(natural_catalog):
    reply = respond(
        "¿Y quién la dirige?",
        natural_catalog,
        context_ids=["row-first"],
    )

    assert_ids(reply, ["row-first"])
    assert reply.rows.iloc[0].directors == "Marta Soler"
    assert "Marta Soler" in reply.text


def test_followup_with_multiple_previous_results_requests_disambiguation(natural_catalog):
    reply = respond(
        "¿Y quién la dirige?",
        natural_catalog,
        context_ids=["row-first", "row-second"],
    )

    assert reply.rows.empty
    assert reply.context_ids == ["row-first", "row-second"]
    assert any(
        clue in reply.text.casefold()
        for clue in ("cuál", "cual", "concreta", "especifica", "título", "titulo")
    )


def test_count_intent_wins_over_dataset_summary_word(natural_catalog):
    reply = respond("¿Cuántas películas hay en todo tu dataset?", natural_catalog)

    assert str(len(natural_catalog)) in reply.text
    assert reply.rows.empty


def test_empty_filters_report_zero_without_unrelated_rows(natural_catalog):
    count = respond("¿Cuántas películas de terror hay en 1901?", natural_catalog)
    listing = respond("Muéstrame películas de terror de 1901", natural_catalog)

    assert "0" in count.text
    assert count.rows.empty
    assert listing.rows.empty
    assert count.context_ids == []
    assert listing.context_ids == []


def test_unknown_explicit_title_never_falls_back_to_year_matches(natural_catalog):
    reply = respond("Dime la sinopsis de Película Fantasma de 1999", natural_catalog)

    assert reply.rows.empty
    assert reply.context_ids == []
    assert "Un Verano Distinto" not in reply.text
    assert any(word in reply.text.casefold() for word in ("no encuentro", "sin coincidencias"))


@pytest.mark.parametrize(
    "message",
    [
        "'; DROP TABLE movies; SELECT * FROM secrets; --",
        "UPDATE movies SET title='owned' WHERE 1=1;",
        "__import__('os').environ.get('MOVIEFLIX_TEST_SECRET')",
    ],
)
def test_malicious_looking_input_cannot_execute_mutate_or_leak(
    natural_catalog, monkeypatch, tmp_path, message
):
    marker = tmp_path / "must-not-exist.txt"
    fake_secret = "fake-secret-only-for-this-test"
    monkeypatch.setenv("MOVIEFLIX_TEST_SECRET", fake_secret)
    before = natural_catalog.copy(deep=True)

    reply = respond(f"{message} {marker}", natural_catalog)

    pd.testing.assert_frame_equal(natural_catalog, before)
    assert not marker.exists()
    assert fake_secret not in reply.text
    assert reply.rows.empty

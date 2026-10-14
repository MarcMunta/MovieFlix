from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import pytest

from assistant import parse_draft, respond
from dataset import COLUMNS, export_csv, read_catalog
from store import MovieStore, combined_catalog, validate_movie, write_access
from train import FEATURES, build_pipeline, training_data


@pytest.fixture
def base():
    return pd.DataFrame(
        [
            dict(
                zip(
                    COLUMNS,
                    [
                        "1",
                        "Inception",
                        2010,
                        148,
                        "Action; Sci-Fi",
                        "A thief enters dreams.",
                        "Christopher Nolan",
                        "Leonardo DiCaprio",
                        "USA",
                        "English",
                        8.8,
                        10000,
                        "movie",
                        "Kaggle",
                        None,
                    ],
                    strict=True,
                )
            ),
            dict(
                zip(
                    COLUMNS,
                    [
                        "2",
                        "Arrival",
                        2016,
                        116,
                        "Drama; Sci-Fi",
                        "A linguist meets aliens.",
                        "Denis Villeneuve",
                        "Amy Adams",
                        "USA",
                        "English",
                        7.9,
                        5000,
                        "movie",
                        "Kaggle",
                        None,
                    ],
                    strict=True,
                )
            ),
            dict(
                zip(
                    COLUMNS,
                    [
                        "3",
                        "Unknown",
                        2010,
                        100,
                        "Drama",
                        "A person searches for home.",
                        "",
                        "",
                        "",
                        "",
                        float("nan"),
                        float("nan"),
                        "movie",
                        "Kaggle",
                        None,
                    ],
                    strict=True,
                )
            ),
        ]
    )


@pytest.fixture
def draft():
    return {
        "title": "Nueva película",
        "year": 2026,
        "runtime": 100,
        "genres": "Drama",
        "plot": "Una familia vuelve a reunirse después de muchos años.",
    }


def test_counts_filters_and_missing_ratings(base):
    assert "3" in respond("¿Cuántas películas hay?", base).text
    assert "1" in respond("Cuántas películas de ciencia ficción de 2010", base).text
    assert len(respond("Películas de ciencia ficción", base).rows) == 2
    average = respond("valoración media de 2010", base).text
    assert "8.80" in average and "sin nota: 1" in average
    assert (
        "columnas" not in respond("¿Qué información tienes?", base).text
    )  # Real summary, not echo.
    assert len(respond("mejores películas de drama", base).rows) == 1


def test_search_and_no_match(base):
    assert respond('busca "Inception"', base).rows.iloc[0].title == "Inception"
    assert len(respond("películas de Christopher Nolan", base).rows) == 1
    assert respond('sinopsis de "Arrival"', base).rows.iloc[0]["plot"] == "A linguist meets aliens."
    assert "No encuentro" in respond("xyzzy-not-a-movie", base).text
    assert respond("películas de ciencia ficción de 2025", base).rows.empty


def test_chat_draft_is_only_a_draft(base, tmp_path):
    message = (
        "añade título=Prueba de chat | año=2026 | duración=100 | género=drama | "
        "sinopsis=Una familia se reúne después de muchos años."
    )
    reply = respond(message, base)
    store = MovieStore(tmp_path / "test.sqlite")
    assert reply.draft["title"] == "Prueba de chat"
    assert "Todavía no" in reply.text
    assert store.read().empty
    parsed = validate_movie(reply.draft, {"Drama"})
    assert parsed.year == 2026
    assert "formulario" in respond("¿Cómo añado una película?", base).text
    with pytest.raises(ValueError, match="desconocido"):
        parse_draft("añade título=A | password=secret-test-value")


@pytest.mark.parametrize(
    "field,value",
    [
        ("title", ""),
        ("plot", "corto"),
        ("year", True),
        ("year", "1900.5"),
        ("year", 1799),
        ("year", 2500),
        ("runtime", 0),
        ("runtime", 100.5),
        ("genres", "Inventado"),
        ("genres", ""),
        ("imdb_rating", -1),
        ("imdb_rating", 11),
        ("imdb_rating", "nan"),
        ("imdb_rating", True),
        ("title", "control\x00"),
        ("plot", {"bad": "type"}),
    ],
)
def test_validation_rejects_malformed_records(draft, field, value):
    with pytest.raises(ValueError):
        validate_movie(draft | {field: value}, {"Drama", "Action"})


def test_add_persists_and_duplicate_is_rejected(base, draft, tmp_path, monkeypatch):
    monkeypatch.delenv("RENDER", raising=False)
    path = tmp_path / "test.sqlite"
    store = MovieStore(path)
    identifier = store.add(draft, base)
    reopened = MovieStore(path)
    added = combined_catalog(base, reopened)
    assert len(added) == 4 and identifier in set(added.id)
    assert added.iloc[-1]["source"].startswith("Alta manual")
    assert added.iloc[-1].imdb_rating is None or pd.isna(added.iloc[-1].imdb_rating)
    assert len(base) == 3
    with pytest.raises(ValueError, match="Ya existe"):
        store.add(draft | {"title": "  NUEVA PELÍCULA "}, base)
    with pytest.raises(ValueError, match="Ya existe"):
        store.add(draft | {"title": "Inception", "year": 2010}, base)


def test_concurrent_duplicate_is_atomic(base, draft, tmp_path, monkeypatch):
    monkeypatch.delenv("RENDER", raising=False)
    store = MovieStore(tmp_path / "test.sqlite")

    def add():
        try:
            store.add(draft, base)
            return "saved"
        except ValueError:
            return "duplicate"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: add(), range(2)))
    assert sorted(results) == ["duplicate", "saved"]
    assert len(store.read()) == 1


def test_render_fail_closed_and_authentication(base, draft, tmp_path, monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("MOVIEFLIX_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("MOVIEFLIX_ADMIN_PASSWORD", raising=False)
    assert not write_access()[0]
    with pytest.raises(PermissionError):
        MovieStore(tmp_path / "test.sqlite").add(draft, base)
    monkeypatch.setenv("MOVIEFLIX_DATA_DIR", "/var/data")
    assert not write_access()[0]
    monkeypatch.setenv("MOVIEFLIX_ADMIN_PASSWORD", "fake-test-password")
    assert not write_access("wrong")[0]
    assert write_access("fake-test-password")[0]


def test_safe_export(base):
    injected = base.copy()
    injected.loc[0, "title"] = ' =HYPERLINK("malicious")'
    assert "' =HYPERLINK" in export_csv(injected).decode("utf-8-sig")


def test_read_only_catalog_does_not_create_storage(tmp_path):
    path = tmp_path / "missing" / "test.sqlite"
    assert MovieStore(path).read().empty
    assert not path.parent.exists()


def test_manual_rating_does_not_change_imdb_average(base, draft, tmp_path):
    store = MovieStore(tmp_path / "test.sqlite")
    store.add(draft | {"imdb_rating": 10}, base)
    catalog = combined_catalog(base, store)
    assert pd.isna(catalog.iloc[-1].imdb_rating)
    assert catalog.iloc[-1].manual_rating == 10
    assert "8.35" in respond("valoración media", catalog).text


def test_unknown_environment_is_read_only(monkeypatch, tmp_path):
    monkeypatch.delenv("MOVIEFLIX_MODE")
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.setenv("MOVIEFLIX_DATA_DIR", str(tmp_path))
    assert not write_access()[0]


def test_single_bound_years_and_quoted_intent_words(base):
    assert "2" in respond("cuántas películas hasta 2010", base).text
    assert "3" in respond("cuántas películas desde 2010", base).text
    copy = base.copy()
    copy.loc[0, "title"] = "Top Gun"
    assert respond('busca "Top Gun"', copy).rows.iloc[0].title == "Top Gun"


def test_comedy_does_not_trigger_average_intent(base):
    copy = base.copy()
    copy.loc[1, "genres"] = "Comedy"
    reply = respond("películas de comedia", copy)
    assert len(reply.rows) == 1
    assert reply.rows.iloc[0].title == "Arrival"


def test_training_has_no_target_leakage_and_deduplicates():
    from sklearn.tree import DecisionTreeClassifier

    frame = read_catalog()
    eligible = training_data(frame)
    assert not eligible.plot_key.duplicated().any()
    assert set(FEATURES) == {"plot", "year", "runtime"}
    assert "genres" not in FEATURES and "imdb_rating" not in FEATURES
    pipeline = build_pipeline(DecisionTreeClassifier(random_state=42))
    small = eligible.head(100)
    pipeline.fit(small[FEATURES], small.target)
    vocabulary = pipeline["features"].named_transformers_["text"].vocabulary_
    assert "heldoutonlywordzz" not in vocabulary
    outputs = pipeline.predict(
        pd.DataFrame([{"plot": "heldoutonlywordzz space adventure", "year": 2026, "runtime": None}])
    )
    assert len(outputs) == 1

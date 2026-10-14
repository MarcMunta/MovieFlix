"""Sistema experto: consultas explícitas; nunca evalúa Python ni SQL del usuario."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

import pandas as pd

from dataset import movie_key, normalize

GENRE_ALIASES = {
    "accion": "Action",
    "aventura": "Adventure",
    "animacion": "Animation",
    "biografia": "Biography",
    "comedia": "Comedy",
    "crimen": "Crime",
    "documental": "Documentary",
    "drama": "Drama",
    "familia": "Family",
    "fantasia": "Fantasy",
    "terror": "Horror",
    "horror": "Horror",
    "musical": "Musical",
    "misterio": "Mystery",
    "romance": "Romance",
    "romantica": "Romance",
    "ciencia ficcion": "Sci-Fi",
    "sci fi": "Sci-Fi",
    "sci-fi": "Sci-Fi",
    "deporte": "Sport",
    "suspense": "Thriller",
    "thriller": "Thriller",
    "guerra": "War",
    "western": "Western",
    "historia": "History",
    "corto": "Short",
}
FIELD_ALIASES = {
    "titulo": "title",
    "title": "title",
    "ano": "year",
    "year": "year",
    "duracion": "runtime",
    "runtime": "runtime",
    "genero": "genres",
    "generos": "genres",
    "genres": "genres",
    "sinopsis": "plot",
    "plot": "plot",
    "director": "directors",
    "directors": "directors",
    "reparto": "cast",
    "cast": "cast",
    "pais": "countries",
    "countries": "countries",
    "idioma": "languages",
    "languages": "languages",
    "nota": "imdb_rating",
    "imdb_rating": "imdb_rating",
}


@dataclass
class Reply:
    text: str
    rows: pd.DataFrame = field(default_factory=pd.DataFrame)
    draft: dict | None = None
    context_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.context_ids and "id" in self.rows:
            self.context_ids = self.rows["id"].astype(str).tolist()


def mentions(query: str, phrases: tuple[str, ...]) -> bool:
    """Las intenciones son palabras completas, no partes de nombres o géneros."""
    return any(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", query) for phrase in phrases)


def question_body(message: str) -> str:
    """Quita cortesía sin perder la petición ni alterar valores de una ficha."""
    body = message.strip().strip("¿¡?!.,;: ")
    prefix = re.compile(
        r"^(?:hola|buenos d[ií]as|buenas tardes|buenas noches|buenas|por favor|"
        r"ahora|dime|mu[eé]strame|ens[eé]ñame|dame|puedes decirme|podr[ií]as decirme)\b[\s,:]*",
        re.IGNORECASE,
    )
    while prefix.match(body):
        body = prefix.sub("", body, count=1).lstrip("¿¡ ")
    return body.rstrip("?!.,;: ")


def requested_field(query: str) -> str | None:
    patterns = (
        ("directors", r"\b(?:director(?:a|es)?|direccion|dirigio|dirige|dirigida|dirigido)\b"),
        ("plot", r"\b(?:sinopsis|argumento|trama|de que trata|resumen de)\b"),
        ("cast", r"\b(?:reparto|actores|actrices|actua|actuan|protagoniza)\b"),
        ("runtime", r"\b(?:duracion|cuanto dura|minutos dura)\b"),
        ("year", r"\b(?:que ano|ano es|ano de|ano tiene|cuando se estreno|el ano|su ano)\b"),
        ("genres", r"\b(?:que genero|generos tiene|genero es|su genero|el genero)\b"),
        ("imdb_rating", r"\b(?:que nota|que puntuacion|que valoracion|su nota|la nota)\b"),
        ("countries", r"\b(?:que pais|paises|su pais|el pais)\b"),
        ("languages", r"\b(?:que idioma|idiomas|su idioma|el idioma)\b"),
    )
    return next((name for name, pattern in patterns if re.search(pattern, query)), None)


def title_words(text: str) -> str:
    return " ".join(re.findall(r"\w+", normalize(text)))


@lru_cache(maxsize=2)
def title_index(titles: tuple[str, ...]) -> tuple[dict[str, list[int]], int]:
    """Índice de títulos/alias reales; se reconstruye cuando cambia el catálogo."""
    lookup: dict[str, list[int]] = {}
    longest = 1
    for position, title in enumerate(titles):
        canonical = title_words(title)
        alias = re.sub(r"^(?:the|a|an|el|la|los|las|un|una)\s+", "", canonical)
        for key in {canonical, alias} - {""}:
            lookup.setdefault(key, []).append(position)
            longest = max(longest, len(key.split()))
    return lookup, longest


def find_titles(query: str, frame: pd.DataFrame, quoted: str | None = None) -> pd.DataFrame:
    lookup, longest = title_index(tuple(frame.title))
    if quoted is not None:
        positions = lookup.get(title_words(quoted), [])
        return frame.iloc[positions]
    words = title_words(query).split()
    stop = {"a", "i", "the", "el", "la", "y", "de", "que", "no", "si", "me", "mi", "en"}
    for size in range(min(longest, len(words)), 0, -1):
        for start in range(len(words) - size + 1):
            term = " ".join(words[start : start + size])
            if term in stop:
                continue
            if term in lookup:
                return frame.iloc[lookup[term]]
    return frame.iloc[:0]


def record_reply(rows: pd.DataFrame, prefix: str = "", attribute: str | None = None) -> Reply:
    if rows.empty:
        return Reply("No hay películas para esos filtros.")
    if len(rows) > 1:
        titles = "\n".join(
            f"{i}. {r.title} ({int(r.year)})" for i, (_, r) in enumerate(rows.iterrows(), 1)
        )
        return Reply(f"{prefix}\n{titles}".strip(), rows)
    row = rows.iloc[0]
    heading = f"{row.title} ({int(row.year)})"
    labels = {
        "directors": "Dirección",
        "plot": "Sinopsis",
        "cast": "Reparto",
        "runtime": "Duración (minutos)",
        "year": "Año",
        "genres": "Géneros",
        "imdb_rating": "Valoración IMDb",
        "countries": "Países",
        "languages": "Idiomas",
    }
    if attribute:
        value = row[attribute]
        available = not pd.isna(value) and str(value).strip() != ""
        detail = str(int(value)) if attribute in {"year", "runtime"} and available else str(value)
        content = (
            f"{labels[attribute]}: {detail}"
            if available
            else f"{labels[attribute]}: no consta en el dataset."
        )
    else:
        content = (
            f"Géneros: {row.genres or 'no constan'}. Dirección: {row.directors or 'no consta'}."
        )
    return Reply(f"{prefix}\n{heading}\n{content}".strip(), rows)


def select_records(query: str, frame: pd.DataFrame) -> Reply | None:
    """Posición física y orden cronológico son operaciones distintas."""
    ordinal = re.search(r"\b(primer[ao]?s?|segund[oa]|tercer[ao]?|ultim[oa]s?)\b", query)
    oldest = mentions(query, ("mas antigua", "mas antiguas", "mas viejo", "mas vieja"))
    newest = mentions(
        query, ("mas reciente", "mas recientes", "mas nueva", "mas nuevas", "mas nuevo")
    )
    if not (ordinal or oldest or newest):
        return None
    filtered = filter_catalog(frame, query)
    if filtered.empty:
        return Reply("No hay películas para esos filtros.")
    count_match = re.search(r"(?:primer[oa]s|ultim[oa]s|las?|los?)\s+(\d+)\b", query)
    count = int(count_match.group(1)) if count_match else 1
    if not 1 <= count <= 50:
        return Reply("Puedo mostrar entre 1 y 50 registros cada vez.")
    if oldest or newest:
        order = filtered.sort_values("year", ascending=oldest, kind="stable")
        label = (
            "Más antiguas por año registrado:" if oldest else "Más recientes por año registrado:"
        )
        return record_reply(order.head(count), label, requested_field(query))
    word = ordinal.group(1)
    if word.startswith("ultim"):
        rows, label = filtered.tail(count), "Últimos registros según el orden del catálogo:"
    else:
        position = 1 if word.startswith("segund") else 2 if word.startswith("tercer") else 0
        rows = filtered.iloc[position : position + count]
        if rows.empty:
            return Reply(
                f"No existe esa posición: solo hay {len(filtered)} registros para esos filtros."
            )
        label = "Registros según el orden del catálogo (no por fecha de estreno):"
    return record_reply(rows, label, requested_field(query))


def similar_movies(reference: pd.Series, frame: pd.DataFrame) -> Reply:
    """Sugerencias explicables con atributos registrados, sin atribuirles criterio de LLM."""
    genres = set(reference.genres.split("; ")) - {""}
    candidates = frame.loc[frame.id.ne(reference.id)].copy()
    overlap = candidates.genres.str.split("; ").map(
        lambda gs: len(genres & set(gs)) / max(1, len(genres | set(gs)))
    )
    candidates["similarity"] = (
        overlap * 3
        + (1 / (1 + (candidates.year - reference.year).abs())) * 0.2
        + (1 / (1 + (candidates.runtime - reference.runtime).abs())).fillna(0) * 0.1
    )
    candidates = candidates.loc[overlap.gt(0)].sort_values(
        "similarity", ascending=False, kind="stable"
    )
    candidates["movie_key"] = [
        movie_key(t, int(y)) for t, y in zip(candidates.title, candidates.year, strict=True)
    ]
    candidates = candidates.loc[
        candidates.movie_key.ne(movie_key(reference.title, int(reference.year)))
    ].drop_duplicates("movie_key")
    return record_reply(
        candidates.head(5),
        f"Sugerencias relacionadas con {reference.title}, por géneros, año y duración. "
        "Estos criterios no garantizan un argumento parecido:",
    )


def parse_draft(message: str) -> dict:
    body = re.sub(
        r"^(anade|agrega|añade|añadir|agregar)\s*(pelicula|película)?\s*:?\s*",
        "",
        message,
        flags=re.I,
    )
    result = {}
    for part in body.split("|"):
        if "=" not in part:
            raise ValueError("Usa campos nombre=valor separados por |.")
        name, value = part.split("=", 1)
        key = FIELD_ALIASES.get(normalize(name))
        if not key or key in result:
            raise ValueError(f"Campo desconocido o repetido: {name.strip()}")
        value = value.strip()
        if key == "genres":
            value = "; ".join(
                GENRE_ALIASES.get(normalize(g), g.strip()) for g in re.split(r"[,;]", value)
            )
        result[key] = value
    return result


def filter_catalog(frame: pd.DataFrame, message: str) -> pd.DataFrame:
    q = normalize(message)
    filtered = frame
    years = [int(y) for y in re.findall(r"\b(18\d{2}|19\d{2}|20\d{2}|21\d{2})\b", q)]
    if years:
        if len(years) >= 2 and any(w in q for w in ("entre", "desde", "hasta")):
            filtered = filtered[filtered.year.between(min(years), max(years))]
        elif "despues" in q or "posterior" in q:
            filtered = filtered[filtered.year > years[0]]
        elif "antes" in q or "anterior" in q:
            filtered = filtered[filtered.year < years[0]]
        elif "desde" in q:
            filtered = filtered[filtered.year >= years[0]]
        elif "hasta" in q:
            filtered = filtered[filtered.year <= years[0]]
        else:
            filtered = filtered[filtered.year.isin(years)]
    known = set(frame.genres.str.split("; ").explode()) - {""}
    aliases = GENRE_ALIASES | {normalize(g): g for g in known}
    matched = {
        genre
        for alias, genre in aliases.items()
        if re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", q)
    }
    if matched:
        filtered = filtered.loc[
            filtered.genres.str.split("; ").map(lambda genres: bool(set(genres) & matched))
        ]
    return filtered


def respond(message: str, frame: pd.DataFrame, context_ids: list[str] | None = None) -> Reply:
    if not isinstance(message, str) or not 1 <= len(message.strip()) <= 3000:
        return Reply("Escribe una pregunta de entre 1 y 3.000 caracteres.")
    body = question_body(message)
    q = normalize(body)
    if not q or q in {"que tal", "como estas", "buen dia", "buenos dias"}:
        return Reply(
            "¡Hola! Puedes preguntarme por la primera película, la más antigua, "
            "una sinopsis o un director. Por ejemplo: ¿de qué trata The Matrix?"
        )
    if frame.empty:
        return Reply("El catálogo está vacío. Añade una película para poder consultarlo.")
    # Explicit titles override intent words and year/genre words inside their names.
    quoted = re.search(r'["“](.+?)["”]', message)
    if re.match(r"^(anade|agrega|anadir|agregar)\b", q) and "=" in message:
        try:
            draft = parse_draft(body)
            return Reply(
                "Ficha preparada. Revisa los datos y pulsa Guardar película. "
                "Todavía no se ha añadido al catálogo.",
                draft=draft,
            )
        except ValueError as error:
            return Reply(str(error))
    # Resolve concrete requests before general words such as "dataset" or "información".
    attribute = requested_field(q)
    if quoted:
        rows = find_titles(q, frame, quoted.group(1))
        if len(rows) == 1 and mentions(q, ("parecidas", "similares", "recomiendame", "recomienda")):
            return similar_movies(rows.iloc[0], frame)
        return (
            record_reply(rows.head(10), attribute=attribute)
            if not rows.empty
            else Reply("No encuentro ese título en el catálogo.")
        )
    if selection := select_records(q, frame):
        return selection
    statistics = mentions(
        q,
        (
            "cuantas",
            "cuantos",
            "cantidad",
            "total",
            "numero de",
            "media",
            "promedio",
            "top",
            "mejores",
            "mejor valoradas",
        ),
    )
    filtered = filter_catalog(frame, q)
    listing = mentions(q, ("peliculas", "titulos", "registros")) and not statistics
    if listing and len(filtered) != len(frame):
        return record_reply(
            filtered.sort_values("imdb_rating", ascending=False, na_position="last").head(10),
            f"Hay {len(filtered):,} registros para esos filtros. Mostrando hasta 10:",
        )
    if not statistics:
        rows = find_titles(q, frame)
        if not rows.empty:
            if (
                mentions(q, ("parecidas", "similares", "recomiendame", "recomienda"))
                and len(rows) == 1
            ):
                return similar_movies(rows.iloc[0], frame)
            return record_reply(rows.head(10), attribute=attribute)
        followup = q.startswith("y ") or mentions(
            q,
            (
                "esa pelicula",
                "esta pelicula",
                "quien la",
                "su ano",
                "su director",
                "de que ano es",
                "cuanto dura",
            ),
        )
        if attribute and followup:
            previous = frame.loc[frame.id.astype(str).isin(context_ids or [])]
            if len(previous) == 1:
                return record_reply(previous, attribute=attribute)
            if len(previous) > 1:
                return Reply(
                    "¿De cuál de las películas quieres ese dato? Indica su título.",
                    context_ids=previous.id.astype(str).tolist(),
                )
            return Reply("Indica el título de la película para consultar ese dato.")
        if attribute:
            return Reply(
                "No encuentro ese título. Indica el nombre de la película; no voy a sustituirla por otro resultado."
            )
    if any(word in q for word in ("anadir", "anado", "agregar", "agrego", "anade", "agrega")):
        return Reply(
            "Abre Añadir película para usar el formulario, o escribe:\n\n"
            "añade título=Mi película | año=2026 | duración=100 | género=Drama | "
            "sinopsis=Una familia vuelve a encontrarse después de muchos años.\n\n"
            "Siempre se muestra una ficha para revisar antes de guardar."
        )
    if not statistics and mentions(
        q,
        (
            "que informacion tienes",
            "que datos tienes",
            "que informacion hay",
            "que contiene",
            "que incluye",
            "columnas",
            "resume el dataset",
            "resumen del dataset",
            "describe el dataset",
            "que puedes hacer",
        ),
    ):
        return Reply(
            f"Tengo {len(frame):,} registros, desde {int(frame.year.min())} hasta "
            f"{int(frame.year.max())}. Incluyen título, año, duración, géneros, sinopsis, "
            "dirección, reparto, países, idiomas, tipo, valoración y votos IMDb cuando existen. "
            f"Hay {int(frame.imdb_rating.isna().sum()):,} registros sin valoración. "
            "Puedo buscar títulos, contar películas, filtrar por género/año, calcular medias "
            "y mostrar las mejor valoradas. Las altas manuales se identifican por su origen."
        )
    if any(w in q for w in ("generos disponibles", "que generos", "lista de generos")):
        counts = frame.genres.str.split("; ").explode()
        counts = (
            counts[counts.ne("")].value_counts().rename_axis("Género").reset_index(name="Películas")
        )
        return Reply("Géneros registrados; una película puede contar en varios géneros.", counts)
    filtered = filter_catalog(frame, q)
    listing = mentions(q, ("peliculas", "titulos", "registros")) and not statistics
    if listing and len(filtered) != len(frame):
        return record_reply(
            filtered.sort_values("imdb_rating", ascending=False, na_position="last").head(10),
            f"Hay {len(filtered):,} registros para esos filtros. Mostrando hasta 10:",
        )
    if mentions(q, ("cuantas", "cuantos", "cantidad", "total", "numero de")):
        return Reply(
            f"Hay {len(filtered):,} registros que cumplen esos filtros. "
            "El catálogo incluye películas y algunas series."
        )
    if mentions(q, ("media", "promedio", "valoracion media")):
        rated = filtered.imdb_rating.dropna()
        if rated.empty:
            return Reply("No hay valoraciones disponibles para esos filtros.")
        return Reply(
            f"Valoración IMDb media: {rated.mean():.2f}/10, sobre {len(rated):,} "
            f"registros con nota. Excluidos sin nota: {len(filtered) - len(rated):,}."
        )
    if mentions(q, ("mejores", "mejor valoradas", "top", "mejor puntuadas")):
        eligible = filtered[filtered.imdb_votes.ge(1000) & filtered.imdb_rating.notna()]
        rows = eligible.sort_values(["imdb_rating", "imdb_votes"], ascending=False).head(10)
        return Reply(
            "Hasta 10 títulos mejor valorados, con al menos 1.000 votos IMDb. "
            "Las altas sin votos verificados no entran en este ranking.",
            rows,
        )
    if any(w in q for w in ("predice", "predecir", "estimar genero", "clasificar")):
        return Reply(
            "Abre Modelo e introduce una sinopsis, año y duración. "
            "Random Forest y Árbol de Decisión estimarán el primer género registrado. "
            "Es una predicción, no un dato confirmado."
        )
    if filtered.empty:
        return Reply("No hay películas para esos filtros.", filtered)
    needle = re.sub(
        r"^(?:buscar pelicula|busca(?:r)?|sinopsis de|informacion (?:de|sobre)|"
        r"hablame de|quien dirige|peliculas (?:de|con)|director|reparto de)\s+",
        "",
        q,
    )
    search_frame = filtered
    texts = (
        search_frame[["title", "directors", "cast"]].fillna("").agg(" ".join, axis=1).map(normalize)
    )
    exact = search_frame[search_frame.title.map(normalize).eq(needle)]
    matches = exact if not exact.empty else search_frame[texts.str.contains(needle, regex=False)]
    if not matches.empty:
        return Reply(
            f"Encontré {len(matches):,} coincidencias. Mostrando hasta 10 fichas del catálogo.",
            matches.head(10),
        )
    if len(filtered) != len(frame):
        return Reply(
            f"Hay {len(filtered):,} registros para esos filtros. Mostrando hasta 10.",
            filtered.sort_values("imdb_rating", ascending=False, na_position="last").head(10),
        )
    return Reply(
        "No encuentro una coincidencia. Prueba un título entre comillas, "
        "«películas de ciencia ficción de 2010», «cuántas películas hay», "
        "«qué información tienes» o «mejores películas de drama». "
        "Este chat usa reglas y búsquedas; no genera respuestas con un LLM."
    )

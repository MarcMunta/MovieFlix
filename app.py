"""MovieFlix: adaptación del ejemplo docente a catálogo de películas y sistema experto."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import nullcontext
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from analyst import AnalysisError, ask_dataset
from assistant import respond
from dataset import CATALOG_PATH, ROOT, export_csv, read_catalog
from demo_access import DemoLimitError, DemoQuota
from model_providers import ModelClient, ProviderError, is_loopback_url
from model_settings import get_model_config, render_model_settings
from prediction import PredictionError, run_predictions
from store import MovieStore, combined_catalog, validate_movie, write_access

st.set_page_config(page_title="MovieFlix · Tu catálogo", layout="wide")


@st.cache_data
def load_base(path: str, modified: int) -> pd.DataFrame:
    return read_catalog(Path(path))


@st.cache_resource
def demo_quota() -> DemoQuota:
    return DemoQuota()


def show_rows(rows: pd.DataFrame) -> None:
    if rows.empty:
        return
    if "title" not in rows:
        st.dataframe(rows, hide_index=True, width="stretch")
        return
    columns = [
        "title",
        "year",
        "genres",
        "runtime",
        "imdb_rating",
        "manual_rating",
        "directors",
        "source",
    ]
    labels = {
        "title": "Título",
        "year": "Año",
        "genres": "Géneros",
        "runtime": "Minutos",
        "imdb_rating": "IMDb",
        "manual_rating": "Nota manual",
        "directors": "Dirección",
        "source": "Origen",
    }
    st.dataframe(rows[columns].rename(columns=labels), hide_index=True, width="stretch")
    with st.expander("Leer sinopsis y reparto"):
        for _, row in rows.head(10).iterrows():
            st.text(f"{row.title} ({int(row.year)})")
            st.text(row["plot"] or "Sin sinopsis disponible.")
            st.caption(f"Reparto: {row['cast'] or 'No disponible'}")


def save_draft(draft: dict) -> None:
    try:
        identifier = store.add(draft, base, st.session_state.get("edit_password", ""))
    except (ValueError, PermissionError) as error:
        st.error(str(error))
    except sqlite3.Error:
        st.error("No se pudo guardar. Comprueba el disco y vuelve a intentarlo.")
    else:
        st.session_state.pop("draft", None)
        selected_draft = {"Chat guiado": "guided_draft", "Chat con IA": "ai_draft"}.get(
            st.session_state.get("navigation")
        )
        if selected_draft:
            st.session_state.pop(selected_draft, None)
        st.session_state["saved_notice"] = f"Película guardada. Referencia: {identifier}"
        st.rerun()


if not CATALOG_PATH.exists():
    st.error("Falta el catálogo. Ejecuta python prepare_data.py --download.")
    st.stop()
try:
    base = load_base(str(CATALOG_PATH), CATALOG_PATH.stat().st_mtime_ns)
    store = MovieStore()
    frame = combined_catalog(base, store)
except (OSError, ValueError, sqlite3.Error):
    st.error("No se pudo abrir el catálogo o las altas. Comprueba los archivos y permisos.")
    st.stop()

genres = sorted(set(base.genres.str.split("; ").explode()) - {""})
with st.sidebar:
    st.title("MovieFlix")
    st.caption("Explora tu catálogo")
    page = st.radio(
        "Sección",
        ["Chat guiado", "Chat con IA", "Catálogo", "Añadir película", "Modelo", "Configuración"],
        label_visibility="collapsed",
        key="navigation",
    )
    st.divider()
    st.caption(f"{len(frame):,} películas y series · {len(frame) - len(base)} altas manuales")
    st.caption("Kaggle · movie-flix")
    if os.environ.get("RENDER", "").lower() == "true" and os.environ.get(
        "MOVIEFLIX_ADMIN_PASSWORD"
    ):
        st.text_input("Contraseña de edición", type="password", key="edit_password")
    can_write, access_note = write_access(st.session_state.get("edit_password", ""))
    st.caption(access_note)

if notice := st.session_state.pop("saved_notice", None):
    st.success(notice)

if page == "Configuración":
    render_model_settings()

elif page in {"Chat guiado", "Chat con IA"}:
    guided = page == "Chat guiado"
    chat_key = "guided" if guided else "ai"
    st.title("Explora con preguntas sugeridas" if guided else "Habla con tu catálogo")
    st.write("Consulta películas, estadísticas y prepara nuevas fichas.")
    try:
        config = None if guided else get_model_config()
    except ValueError:
        st.error(
            "La API de la demo no está configurada correctamente. El administrador debe revisar los secretos de Render."
        )
        st.stop()
    managed = not guided and getattr(config, "server_managed", False)
    if managed:
        st.caption(
            "API gratuita de la demo activa · 2 preguntas/minuto y 30/día compartidas. "
            "Las cuotas del proveedor también se aplican. No necesitas introducir una clave."
        )
    needs_public_api = (
        not guided
        and os.environ.get("RENDER", "").lower() == "true"
        and is_loopback_url(config.base_url)
    )
    if needs_public_api:
        st.info(
            "Abre Configuración para conectar tu propia API en esta sesión. "
            "Para utilizar un modelo local, ejecuta MovieFlix en tu ordenador."
        )
    st.caption(
        "Chat guiado · Consultas directas sin modelo ni API"
        if guided
        else f"Chat con IA · Modelo conectado: {config.model}"
    )
    st.divider()
    chosen = None
    messages = st.session_state.setdefault(f"{chat_key}_messages", [])
    context_ids = st.session_state.get(f"{chat_key}_context", [])
    if guided:
        context = frame.loc[frame.id.astype(str).isin(context_ids)]
        if len(context) == 1:
            title = context.iloc[0].title
            suggestions = [
                ("Sinopsis", f'¿De qué trata "{title}"?'),
                ("Dirección", "¿Y quién la dirige?"),
                ("Año", "¿Y de qué año es?"),
                ("Parecidas", f'Recomiéndame películas parecidas a "{title}"'),
            ]
        elif len(context) > 1:
            suggestions = [
                (str(row.title), f'Háblame de "{row.title}"')
                for _, row in context.head(4).iterrows()
            ]
        else:
            suggestions = [
                ("Primera fila", "Dime la primera película de todo tu dataset"),
                ("Más antigua", "¿Cuál es la película más antigua?"),
                ("Información", "¿Qué información tienes?"),
                ("Géneros", "¿Qué géneros tienes?"),
            ]
        st.caption("Preguntas recomendadas")
        columns = st.columns(2)
        for i, (label, question) in enumerate(suggestions):
            if columns[i % 2].button(label, key=f"suggestion_{i}", width="stretch"):
                chosen = question
    if not messages:
        with st.chat_message("assistant"):
            st.write(
                "Elige una pregunta o escribe una consulta. Las sugerencias se adaptan al resultado."
                if guided
                else "Pregunta libremente sobre los datos. Consultaré el catálogo con el "
                "modelo que hayas conectado en Configuración. Si falta información, te lo diré."
            )
    prompt = (
        st.chat_input(
            "Pregunta sobre el dataset…",
            disabled=needs_public_api,
            key=f"{chat_key}_input",
            max_chars=3000,
            submit_mode="disable",
        )
        or chosen
    )
    if prompt:
        reply = None
        if guided:
            reply = respond(prompt, frame, context_ids=context_ids)
        else:
            try:
                with st.status("Consultando el modelo…", expanded=False) as status:
                    with (
                        demo_quota().reserve() if managed else nullcontext(),
                        ModelClient(config) as client,
                    ):
                        reply = ask_dataset(
                            prompt,
                            frame,
                            client,
                            history=messages,
                            context_ids=context_ids,
                            progress=lambda text: status.update(label=text),
                        )
                    status.update(label="Respuesta basada en el catálogo", state="complete")
            except (ProviderError, AnalysisError, ValueError, DemoLimitError) as error:
                st.error(str(error))
                st.info(
                    "Revisa Configuración o inténtalo de nuevo. El Chat guiado sigue disponible."
                )
        if reply is not None:
            st.session_state[f"{chat_key}_context"] = reply.context_ids
            messages.extend(
                [
                    {"role": "user", "text": prompt},
                    {
                        "role": "assistant",
                        "text": reply.text,
                        "rows": reply.rows,
                        "evidence": getattr(reply, "evidence", []),
                    },
                ]
            )
            if reply.draft is not None:
                st.session_state[f"{chat_key}_draft"] = reply.draft
        del messages[:-40]
        if guided and reply is not None:
            st.rerun()
    for message in messages:
        with st.chat_message(message["role"]):
            st.text(message["text"])
            if "rows" in message:
                show_rows(message["rows"])
            if message.get("evidence"):
                with st.expander("Datos utilizados para responder"):
                    for result in message["evidence"]:
                        st.dataframe(
                            pd.DataFrame(result.rows, columns=result.columns),
                            hide_index=True,
                            width="stretch",
                        )
                        if result.truncated:
                            st.caption(
                                "Resultado limitado a 50 filas; no representa un conteo total."
                            )
    if draft := st.session_state.get(f"{chat_key}_draft"):
        st.subheader("Revisa la nueva ficha")
        st.json(draft)
        try:
            checked = validate_movie(draft, set(genres))
        except ValueError as error:
            st.warning(str(error))
            st.caption("Corrige el mensaje con todos los campos o usa Añadir película.")
        else:
            if st.button("Guardar película", type="primary", disabled=not can_write):
                save_draft(asdict(checked))
        if st.button("Descartar ficha"):
            st.session_state.pop(f"{chat_key}_draft", None)
            st.rerun()
    if messages and st.button("Limpiar conversación"):
        st.session_state[f"{chat_key}_messages"] = []
        st.session_state.pop(f"{chat_key}_context", None)
        st.session_state.pop(f"{chat_key}_draft", None)
        st.rerun()

elif page == "Catálogo":
    st.title("Explora las películas")
    st.caption("Consulta datos registrados. Las valoraciones vacías no se sustituyen por cero.")
    search = st.text_input(
        "Título, dirección o reparto", placeholder="Por ejemplo: Christopher Nolan"
    )
    left, right = st.columns(2)
    genre = left.selectbox("Género", ["Todos", *genres])
    years = right.slider(
        "Años",
        int(frame.year.min()),
        int(frame.year.max()),
        (int(frame.year.min()), int(frame.year.max())),
    )
    filtered = frame[frame.year.between(*years)]
    if genre != "Todos":
        filtered = filtered.loc[filtered.genres.str.split("; ").map(lambda gs: genre in gs)]
    if search.strip() and not filtered.empty:
        text = filtered[["title", "directors", "cast"]].agg(" ".join, axis=1)
        filtered = filtered[text.str.contains(search.strip(), case=False, regex=False)]
    st.write(f"{len(filtered):,} coincidencias")
    if filtered.empty:
        st.info("No hay coincidencias. Prueba otro título o amplía los filtros.")
    else:
        page_number = st.number_input(
            "Página (50 títulos por página)",
            min_value=1,
            max_value=max(1, (len(filtered) + 49) // 50),
            step=1,
        )
        start = (page_number - 1) * 50
        show_rows(filtered.iloc[start : start + 50])
    st.download_button(
        "Descargar catálogo filtrado (CSV)",
        export_csv(filtered),
        file_name="movieflix-filtrado.csv",
        mime="text/csv",
    )
    st.download_button(
        "Descargar catálogo completo con altas",
        export_csv(frame),
        file_name="movieflix-completo.csv",
        mime="text/csv",
    )

elif page == "Añadir película":
    st.title("Añade una película")
    st.write("Completa una ficha nueva. El original de Kaggle se conserva.")
    st.caption("El género debe ser conocido; la nota es opcional y se marcará como alta manual.")
    if not can_write:
        st.info(access_note)
    with st.form("new_movie", clear_on_submit=False):
        title = st.text_input("Título", max_chars=200)
        col1, col2 = st.columns(2)
        year = col1.number_input(
            "Año",
            min_value=1800,
            max_value=datetime.now().year + 5,
            value=datetime.now().year,
            step=1,
        )
        runtime = col2.number_input(
            "Duración (minutos)", min_value=1, max_value=2000, value=100, step=1
        )
        selected_genres = st.multiselect("Géneros (entre 1 y 3)", genres, max_selections=3)
        plot = st.text_area(
            "Sinopsis",
            max_chars=5000,
            help="Al menos 15 caracteres. El modelo se entrenó con sinopsis en inglés.",
        )
        directors = st.text_input("Dirección (opcional)", max_chars=1000)
        cast = st.text_input("Reparto (opcional)", max_chars=1000)
        countries = st.text_input("Países (opcional)", max_chars=1000)
        languages = st.text_input("Idiomas (opcional)", max_chars=1000)
        rating = st.text_input(
            "Valoración (opcional, entre 0 y 10)",
            help="Una nota manual no es una valoración IMDb verificada.",
        )
        submitted = st.form_submit_button(
            "Guardar película", type="primary", disabled=not can_write
        )
    if submitted:
        save_draft(
            {
                "title": title,
                "year": year,
                "runtime": runtime,
                "genres": "; ".join(selected_genres),
                "plot": plot,
                "directors": directors,
                "cast": cast,
                "countries": countries,
                "languages": languages,
                "imdb_rating": rating,
            }
        )

elif page == "Modelo":
    st.title("Estima el género")
    st.write("Compara un Árbol de Decisión con Random Forest, como en el ejemplo de clase.")
    model_path = ROOT / "modelo.joblib"
    if not model_path.exists():
        st.warning("Falta el modelo. Ejecuta python train.py. El resto de la app sigue disponible.")
        st.stop()
    try:
        metadata = json.loads((ROOT / "metrics.json").read_text(encoding="utf-8"))
        if not {"metrics", "trees", "train_rows", "test_rows"} <= metadata.keys():
            raise ValueError("Métricas incompletas.")
    except (OSError, ValueError, KeyError):
        st.error("No se pudieron cargar las métricas. Reentrena con las dependencias del proyecto.")
        st.stop()
    st.caption(
        "Objetivo: primer género del registro. Sinopsis en inglés para mejor compatibilidad."
    )
    with st.form("prediction"):
        synopsis = st.text_area("Sinopsis para clasificar", max_chars=5000)
        left, right = st.columns(2)
        pred_year = left.number_input("Año de la película", 1800, datetime.now().year + 5, 2020)
        pred_runtime = right.number_input("Duración de la película", 1, 2000, 100)
        predicted = st.form_submit_button("Comparar predicciones", type="primary")
    if predicted:
        if len(synopsis.strip()) < 15:
            st.error("Escribe una sinopsis de al menos 15 caracteres.")
        else:
            try:
                with st.spinner("Comparando modelos…"):
                    predictions = run_predictions(
                        {"plot": synopsis, "year": pred_year, "runtime": pred_runtime}
                    )
            except (ValueError, PredictionError) as error:
                st.error(str(error))
            else:
                for column, name, label in zip(
                    st.columns(2),
                    ["decision_tree", "random_forest"],
                    ["Árbol de Decisión", "Random Forest"],
                    strict=True,
                ):
                    result = predictions[name]
                    column.subheader(label)
                    column.write(f"Predicción: {result['prediction']}")
                    column.dataframe(
                        pd.DataFrame(result["ranking"]), hide_index=True, width="stretch"
                    )
                st.caption(
                    "Probabilidades sin calibrar; predicción orientativa, no información confirmada."
                )
    st.subheader("Evaluación con películas no vistas")
    rows = []
    for name, label in (
        ("baseline", "Mayoritaria (referencia)"),
        ("decision_tree", "Árbol de Decisión"),
        ("random_forest", "Random Forest"),
    ):
        metrics = metadata["metrics"][name]
        rows.append(
            {"Modelo": label, "Accuracy": metrics["accuracy"], "F1 macro": metrics["macro_f1"]}
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption(
        f"Train: {metadata['train_rows']:,} · Test: {metadata['test_rows']:,} · "
        f"{metadata['trees']} árboles · Grupos compartidos: {metadata['group_overlap']}"
    )
    with st.expander("Método, resultados y límites"):
        st.write(metadata["split"])
        st.write(metadata["evaluation_note"])
        for limitation in metadata["limitations"]:
            st.write(limitation)
        st.write(
            "El preprocesado TF-IDF y la imputación se ajustan solo con train. "
            "No se usan géneros, valoraciones, premios ni votos como entradas."
        )
        st.write(f"OOB del bosque: {metadata['oob_accuracy']:.3f}")
        st.json(metadata["metrics"]["random_forest"]["report"])
    current_hash = hashlib.sha256(CATALOG_PATH.read_bytes()).hexdigest()
    if current_hash != metadata["catalog_sha256"] or len(frame) > metadata["catalog_rows"]:
        st.info(
            "El catálogo tiene cambios posteriores al entrenamiento. "
            "Las búsquedas ya los incluyen; reentrena para actualizar el modelo."
        )
    st.download_button(
        "Descargar métricas (JSON)",
        json.dumps(metadata, ensure_ascii=False, indent=2),
        file_name="movieflix-metricas.json",
        mime="application/json",
    )

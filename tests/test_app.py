from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def test_app_chat_search_form_prediction(tmp_path, monkeypatch):
    monkeypatch.setenv("MOVIEFLIX_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("RENDER", raising=False)
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=20).run()
    assert not app.exception
    app.chat_input[0].set_value('busca "Inception"').run()
    assert not app.exception and app.dataframe
    app.sidebar.radio[0].set_value("Añadir película").run()
    app.text_input[0].set_value("Ficha de prueba AppTest")
    app.multiselect[0].set_value(["Drama"])
    app.text_area[0].set_value("A family reunites after a long time apart.")
    app.button[0].click().run()
    assert not app.exception
    assert app.success
    from store import MovieStore

    assert len(MovieStore(tmp_path / "additions.sqlite3").read()) == 1
    app.sidebar.radio[0].set_value("Chat guiado").run()
    app.chat_input[0].set_value('busca "Ficha de prueba AppTest"').run()
    assert not app.exception
    assert any("Ficha de prueba AppTest" in str(df.value) for df in app.dataframe)
    app.sidebar.radio[0].set_value("Modelo").run()
    app.text_area[0].set_value("A spaceship crew must survive an alien attack on a distant planet.")
    app.button[0].click().run()
    assert not app.exception
    assert len(app.dataframe) >= 3


def test_cloud_form_cannot_write_without_persistence(tmp_path, monkeypatch):
    monkeypatch.setenv("MOVIEFLIX_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RENDER", "true")
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=20).run()
    app.sidebar.radio[0].set_value("Añadir película").run()
    assert not app.exception
    assert app.button[0].disabled


def test_empty_catalog_filters_with_search(tmp_path, monkeypatch):
    monkeypatch.setenv("MOVIEFLIX_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("RENDER", raising=False)
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=20).run()
    app.sidebar.radio[0].set_value("Catálogo").run()
    app.selectbox[0].set_value("Sci-Fi")
    app.slider[0].set_value((1896, 1896))
    app.text_input[0].set_value("Título sin coincidencias")
    app.run()
    assert not app.exception
    assert app.info


def test_guided_and_ai_chats_keep_independent_histories(tmp_path, monkeypatch):
    monkeypatch.setenv("MOVIEFLIX_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("RENDER", raising=False)
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=20).run()

    guided_prompt = "¿Qué información tienes?"
    app.chat_input[0].set_value(guided_prompt).run()
    guided_messages = list(app.session_state["guided_messages"])
    assert len(guided_messages) == 2
    assert guided_messages[0] == {"role": "user", "text": guided_prompt}

    app.sidebar.radio[0].set_value("Chat con IA").run()
    assert not app.exception
    assert app.session_state["ai_messages"] == []
    assert list(app.session_state["guided_messages"]) == guided_messages

    app.session_state["ai_messages"] = [
        {"role": "user", "text": "Pregunta del chat IA"},
        {"role": "assistant", "text": "Respuesta del chat IA"},
    ]
    app.run()
    assert any(element.value == "Respuesta del chat IA" for element in app.text)

    app.sidebar.radio[0].set_value("Chat guiado").run()
    assert not app.exception
    assert list(app.session_state["guided_messages"]) == guided_messages
    assert app.session_state["ai_messages"][-1]["text"] == "Respuesta del chat IA"
    assert any(element.value == guided_messages[-1]["text"] for element in app.text)
    assert all(element.value != "Respuesta del chat IA" for element in app.text)

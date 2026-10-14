# Publicar MovieFlix en Render

Estado: servicio Free [movieflix-marcm.onrender.com](https://movieflix-marcm.onrender.com) desplegado. Health público HTTP 200 (`ok`), interfaz Streamlit y chat guiado comprobados desde navegador.

Repositorio público: [github.com/MarcMunta/MovieFlix](https://github.com/MarcMunta/MovieFlix), rama main. No subas `data/raw`, `.venv`, `storage`, logs, `.env` ni credenciales. El build usa el catálogo y modelo incluidos; no descarga Kaggle ni reentrena.

## Demo Free: lectura por defecto

`render.yaml` declara Python 3.13.5, plan Free, `MOVIEFLIX_MODE=cloud`, health check `/_stcore/health` y este arranque:

```text
streamlit run app.py --server.port $PORT --server.address 0.0.0.0
```

La demo Free ofrece Chat guiado, catálogo, exportación y predicción. Las altas quedan bloqueadas porque el filesystem efímero perdería cambios. No necesita ninguna API para esas funciones.

**Chat con IA no está conectado por defecto en Render Free.** La configuración inicial apunta a `127.0.0.1:8091`, que dentro de Render es el propio contenedor. Render no puede alcanzar llama.cpp, LM Studio u Ollama que estén en el `localhost` del ordenador del usuario. Tampoco se incluye un LLM en el servicio.

Cada usuario puede abrir **Configuración** y conectar durante su sesión una API propia. Clave, proveedor, modelo, URL y límites quedan solo en esa sesión; Render no los escribe en disco. Las URLs admitidas se muestran en la UI:

- OpenAI: `https://api.openai.com/v1`
- OpenRouter: `https://openrouter.ai/api/v1`
- Groq: `https://api.groq.com/openai/v1`
- Together: `https://api.together.xyz/v1`
- Anthropic: `https://api.anthropic.com/v1`
- Gemini: `https://generativelanguage.googleapis.com/v1beta`

La allowlist bloquea localhost, redes privadas y endpoints personalizados en cloud para reducir riesgo SSRF. Esos destinos siguen disponibles al ejecutar MovieFlix en local. Toda API remota exige clave y HTTPS.

## Variante persistente de pago

`render-persistent.yaml` declara plan Starter, disco de 1 GB montado en `/var/data` y:

- `MOVIEFLIX_MODE=cloud`
- `MOVIEFLIX_DATA_DIR=/var/data`
- `MOVIEFLIX_ADMIN_PASSWORD` como secreto de Render (`sync: false`)

Requiere aceptar el coste antes de crearla. Las altas se guardan en `/var/data/additions.sqlite3`. La configuración IA en Render sigue siendo por usuario y sesión: ni claves ni preferencias se guardan en el disco persistente.

El disco limita el servicio a una instancia. SQLite usa transacciones y basta para esta práctica de baja concurrencia; no es diseño de producción multiinstancia. Consulta precios y límites vigentes de [Render](https://render.com/docs/free) antes de contratar.

## Publicación

1. Confirma que el commit que se quiere desplegar está en el repositorio público.
2. Espera a que `movieflix-marcm` alcance estado **Live** y abre <https://movieflix-marcm.onrender.com>.
3. Verifica <https://movieflix-marcm.onrender.com/_stcore/health>.
4. Abre Chat guiado y pregunta `¿Qué información tienes?`.
5. Busca `Inception`, abre Modelo y ejecuta una predicción.
6. Confirma que **Añadir película** informa que Render Free es de consulta.
7. En Configuración, comprueba que cada URL pública admitida aparece y que localhost o un dominio personalizado se rechazan. Una prueba real de Chat con IA requiere una clave propia; no la pegues en logs, documentación ni capturas.

Para la variante persistente, usa `render-persistent.yaml`, configura el secreto en Render y añade estas pruebas:

1. Autentica la edición y guarda una ficha identificada como prueba.
2. Reinicia el servicio.
3. Comprueba que la ficha sigue presente y que un duplicado título/año se rechaza.
4. Descarga el CSV completo y confirma que la alta figura como manual y su nota no aparece como IMDb.

Solo esas pruebas acreditan despliegue, WebSocket, memoria, arranque y persistencia reales. La validación local no los demuestra.

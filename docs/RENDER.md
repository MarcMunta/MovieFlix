# Publicar MovieFlix en Render

Estado: servicio Free [movieflix-marcm.onrender.com](https://movieflix-marcm.onrender.com) desplegado. Health público HTTP 200 (`ok`), interfaz Streamlit y chat guiado comprobados desde navegador.

Repositorio público: [github.com/MarcMunta/MovieFlix](https://github.com/MarcMunta/MovieFlix), rama main. No subas `data/raw`, `.venv`, `storage`, logs, `.env` ni credenciales. El build usa el catálogo y modelo incluidos; no descarga Kaggle ni reentrena.

## Demo Free: lectura por defecto

`render.yaml` declara Python 3.13.5, plan Free, `MOVIEFLIX_MODE=cloud`, health check `/_stcore/health` y este arranque:

```text
streamlit run app.py --server.port $PORT --server.address 0.0.0.0
```

La demo Free ofrece Chat guiado, catálogo, exportación y predicción. Las altas quedan bloqueadas porque el filesystem efímero perdería cambios. No necesita ninguna API para esas funciones.

**API compartida opcional:** el operador puede activar Groq Free configurando `MOVIEFLIX_LLM_API_KEY` únicamente en Environment de Render. Nunca se copia la clave al código, formulario público, TXT ni paquete. El modelo predeterminado es `openai/gpt-oss-120b`; destino fijo `https://api.groq.com/openai/v1`. `MOVIEFLIX_LLM_MODEL` admite también `openai/gpt-oss-20b` y `qwen/qwen3.8-27b`. No se activan planes de pago ni métodos de pago.

Cuando existe esa variable, Chat con IA usa la API compartida automáticamente. Configuración muestra su disponibilidad y permite volver a ella mediante **Usar API de la demo**. Cambiar el perfil exige una clave propia, incluso para el mismo proveedor: nunca reutiliza la clave del operador.

La demo compartida permite una consulta simultánea, dos intentos por minuto y treinta por día UTC, entre todos sus visitantes. Los intentos fallidos consumen cuota. Este contador vive en memoria y se reinicia al reiniciar el proceso; los límites de la cuenta Groq siguen siendo efectivos. Es una protección básica para la práctica, no un limitador distribuido. Consulta los [límites oficiales de Groq](https://console.groq.com/docs/rate-limits). Las preguntas y resultados del catálogo se transmiten a Groq; no introduzcas información privada.

Sin secreto de servidor, cada usuario puede conectar su API propia. Render no puede alcanzar llama.cpp, LM Studio u Ollama en el `localhost` del ordenador del usuario. No se incluye un LLM en el contenedor.

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
7. Si existe secreto de servidor, abre Chat con IA sin introducir clave y comprueba una respuesta con evidencia SQL. En Configuración, cambia de proveedor y verifica que exige una clave propia; vuelve mediante Usar API de la demo. Sin secreto, la prueba requiere clave propia. No la pegues en logs, documentación ni capturas.

Para la variante persistente, usa `render-persistent.yaml`, configura el secreto en Render y añade estas pruebas:

1. Autentica la edición y guarda una ficha identificada como prueba.
2. Reinicia el servicio.
3. Comprueba que la ficha sigue presente y que un duplicado título/año se rechaza.
4. Descarga el CSV completo y confirma que la alta figura como manual y su nota no aparece como IMDb.

Solo esas pruebas acreditan despliegue, WebSocket, memoria, arranque y persistencia reales. La validación local no los demuestra.

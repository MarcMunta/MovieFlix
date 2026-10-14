# MovieFlix

Aplicación docente en español para explorar el dataset [movie-flix](https://www.kaggle.com/datasets/manaswinsripatnala/movie-flix-dataset), comparar un Árbol de Decisión con Random Forest y añadir películas sin modificar el CSV original. La arquitectura adapta el ejemplo [Sign-Detector-App-Stucom](https://github.com/Abel1002/Sign-Detector-App-Stucom) a Streamlit, scikit-learn, `joblib`, SQLite y Render.

Repositorio público: [github.com/MarcMunta/MovieFlix](https://github.com/MarcMunta/MovieFlix). Demo gratuita en [movieflix-marcm.onrender.com](https://movieflix-marcm.onrender.com). Health HTTP 200 y chat público comprobados; la IA requiere conectar tu modelo local o API propia.

## Funciones

- **Chat guiado:** consultas directas, sugerencias y seguimientos sin modelo ni API.
- **Chat con IA:** preguntas libres mediante un proveedor configurable: OpenAI-compatible (llama.cpp, LM Studio o vLLM), Ollama, Anthropic o Gemini.
- **Consultas verificadas:** el modelo crea un plan JSON y SQL; MovieFlix lo valida y ejecuta solo contra una copia SQLite en memoria y de solo lectura. La respuesta final se redacta únicamente con los resultados obtenidos.
- **Catálogo:** búsquedas, filtros, paginación y exportación CSV.
- **Altas manuales:** formulario o borrador preparado desde cualquiera de los chats. La app valida la ficha y exige revisión y pulsar **Guardar película**; nunca guarda por el mero hecho de conversar.
- **Modelo clásico:** comparación del Árbol y Random Forest para estimar el primer género registrado a partir de sinopsis, año y duración.

MovieFlix no entrena un LLM desde cero. El entrenamiento incluido en `train.py` corresponde exclusivamente a los clasificadores clásicos de scikit-learn.

## Inicio rápido en Windows

Requisitos: Windows, PowerShell, Python 3.13 y acceso a internet solo para la primera instalación de dependencias.

Desde la carpeta del proyecto:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\Iniciar-MovieFlix.ps1
```

El lanzador crea `.venv` e instala `requirements.txt` si hace falta, establece `MOVIEFLIX_MODE=local` y abre Streamlit en <http://127.0.0.1:8510>. La app solo escucha en `127.0.0.1`.

Inicio manual equivalente:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:MOVIEFLIX_MODE = 'local'
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8510
```

El catálogo normalizado y `modelo.joblib` ya forman parte del proyecto; no hace falta descargar Kaggle ni reentrenar para arrancar.

## Configurar Chat con IA

Abre **Configuración**, elige protocolo, URL base y modelo, y prueba la conexión. Ejemplos locales habituales:

- llama.cpp o LM Studio: protocolo OpenAI-compatible y la URL `/v1` expuesta por el servidor.
- Ollama: protocolo Ollama y, normalmente, `http://127.0.0.1:11434`.
- Anthropic o Gemini: endpoint HTTPS del proveedor y clave API.

Las claves escritas en la interfaz se mantienen solo en la sesión de Streamlit y nunca se escriben en `model-config.json`. En local, ese archivo conserva únicamente proveedor, URL, nombre del modelo, timeout y límite de salida mediante escritura atómica; si el disco falla, la configuración sigue activa en la sesión. En Render no se persisten ni claves ni preferencias.

El valor local predeterminado apunta a `http://127.0.0.1:8091/v1`. Debe existir allí un servidor compatible para usar el Chat con IA; si no existe, el Chat guiado y el resto de la app siguen disponibles.

En local se admiten endpoints personalizados válidos, incluidos llama.cpp, LM Studio y Ollama en loopback. En la demo pública, cada usuario puede conectar su propia API durante su sesión, pero solo mediante estas bases HTTPS permitidas para reducir riesgo SSRF:

- OpenAI: `https://api.openai.com/v1`
- OpenRouter: `https://openrouter.ai/api/v1`
- Groq: `https://api.groq.com/openai/v1`
- Together: `https://api.together.xyz/v1`
- Anthropic: `https://api.anthropic.com/v1`
- Gemini: `https://generativelanguage.googleapis.com/v1beta`

La clave remota es obligatoria. Cambiar de destino no reutiliza la clave anterior. El operador puede activar una API Groq gratuita compartida mediante un secreto de Render: consulta [docs/RENDER.md](docs/RENDER.md). Si está activada, Chat con IA funciona sin introducir clave. La clave del operador nunca se utiliza en perfiles personalizados; estos exigen una clave propia.

## Cómo consulta los datos la IA

El flujo está diseñado para reducir invenciones y bloquear escrituras:

1. El modelo devuelve una acción JSON: consultar, preparar borrador, responder sobre capacidades o pedir aclaración.
2. Para datos, puede proponer de una a tres consultas SQL.
3. `query_engine.py` las ejecuta sobre un snapshot SQLite en memoria con `query_only`, autorizador de operaciones/funciones, presupuesto de tiempo, límites internos y máximo de 50 filas por resultado.
4. El redactor recibe la pregunta y los resultados verificados; no puede sustituirlos por conocimiento general del modelo.

Las respuestas siguen dependiendo de que el proveedor obedezca el formato esperado. Consultas inválidas se rechazan y se permite un intento de corrección; no se ejecuta SQL libre sobre la base de altas ni sobre archivos del equipo.

## Altas y persistencia

En local, las altas se guardan de forma transaccional en `storage/additions.sqlite3`, con unicidad por título/año. El CSV de Kaggle se conserva intacto. Las valoraciones introducidas manualmente se almacenan como `manual_rating`, separadas de IMDb.

Las nuevas fichas aparecen enseguida en búsquedas y exportaciones. No cambian el clasificador hasta reentrenar y recargar:

```powershell
$env:MOVIEFLIX_MODE = 'local'
.\.venv\Scripts\python.exe train.py --include-additions
```

## Dataset y modelo

`data/movies.csv` contiene 21.349 películas y series de 1896 a 2016. Es un snapshot histórico. `data/provenance.json` registra origen y hash. Los CSV/ZIP brutos, usuarios, sesiones, comentarios, salas y embeddings se excluyen de la publicación.

El objetivo es el primer género listado, no una etiqueta editorial de género principal. Tras deduplicar sinopsis y agrupar por título/año quedan 19.415 ejemplos elegibles: 11.651 de entrenamiento, 3.884 de validación y 3.880 de test, sin grupos compartidos. TF-IDF e imputación se ajustan solo con train.

| Modelo | Accuracy test | F1 macro |
| --- | ---: | ---: |
| Clase mayoritaria | 30,44 % | 0,0259 |
| Árbol de Decisión | 34,20 % | 0,1521 |
| Random Forest, 160 árboles | 42,37 % | 0,1369 |

Random Forest mejora el acierto global, pero el rendimiento equilibrado por clase sigue siendo bajo. Las probabilidades no están calibradas, el catálogo termina en 2016 y no existe evaluación específica para sinopsis en español. Es una demostración educativa, no un recomendador de precisión garantizada.

El bosque limita cada árbol a 512 hojas por presupuesto operativo de Render Free. Las estructuras de sus árboles ocupan aproximadamente 34 MB frente a unos 166 MB en la versión anterior. El artefacto se guarda sin compresión para permitir carga con `mmap` y reducir el pico de CPU. Este límite se eligió por memoria y operación, no para maximizar la métrica. El split sigue siendo el mismo y su test ya se había consultado en revisiones anteriores: estas cifras describen la configuración actual, pero no constituyen una nueva evaluación ciega.

## Render

`render.yaml` define una demo Free en modo cloud y solo lectura para las altas. Chat guiado, catálogo y predicción no necesitan API. Chat con IA no funciona con el valor local predeterminado: el `localhost` de Render pertenece al contenedor y no puede alcanzar llama.cpp, LM Studio u Ollama ejecutados en el PC. Cada usuario sí puede conectar durante su sesión una API pública de la lista permitida; su clave y preferencias no se persisten.

`render-persistent.yaml` añade un servicio de pago, disco `/var/data` y contraseña de edición para guardar altas. No es necesario para configurar el Chat con IA por sesión. El servicio Free [movieflix-marcm.onrender.com](https://movieflix-marcm.onrender.com) está desplegado y responde al health check público.

En una revisión pública anterior, abrir la pestaña de predicción coincidió con timeout del health check y reinicio del servicio; Render no aportó una señal explícita de OOM. La corrección se verificó en Render: carga ligera de la pantalla, predicción de ambos modelos en subproceso, resultados iguales a local y health HTTP 200 después de iniciar la petición. El bosque reducido, `mmap` y un único worker con timeout mantienen la aplicación disponible. No es una prueba de carga multiusuario.

## Consultas IA comprobadas

Con el proveedor local conectado, el flujo planificador → SQL verificado → redactor respondió correctamente a casos concretos:

- primera fila física: **The Great Train Robbery (1903)**; seguimiento de dirección: **Edwin S. Porter**;
- película más antigua: **The Kiss (1896)**;
- comedias entre 2000 y 2010: **2.487**, valoración IMDb media **6,281302774427**;
- directores registrados de **The Matrix**: **Andy Wachowski; Lana Wachowski**.

Estas pruebas demuestran esos casos sobre el snapshot incluido. No garantizan que cualquier pregunta o cualquier modelo produzca un plan válido; el comportamiento depende de calidad, compatibilidad y disponibilidad del proveedor.

## Verificación

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pip check
```

La suite cubre datos, chat guiado, planificación IA, SQL de solo lectura, proveedores, límites de respuesta, claves no persistidas, concurrencia SQLite y la app Streamlit. El estado y los límites de la última ejecución se documentan en [docs/VERIFICACION.md](docs/VERIFICACION.md).

## Archivos principales

| Archivo | Responsabilidad |
| --- | --- |
| `app.py` | Interfaz Streamlit y confirmación de altas |
| `assistant.py` | Chat guiado y consultas deterministas |
| `analyst.py` | Planificador y redactor del Chat con IA |
| `query_engine.py` | Snapshot SQLite y ejecución de lectura restringida |
| `model_providers.py` | Adaptadores OpenAI-compatible, Ollama, Anthropic y Gemini |
| `model_settings.py` | Configuración sin persistir claves |
| `store.py` | Validación, permisos y altas SQLite transaccionales |
| `train.py` | Entrenamiento reproducible de Árbol y Random Forest |
| `render.yaml` | Demo Free de solo lectura |
| `render-persistent.yaml` | Variante de pago con disco persistente |

## Seguridad y límites

Las altas cloud fallan cerradas: solo se habilitan con `/var/data`, contraseña configurada y contraseña correcta. La configuración IA cloud restringe destinos a una lista HTTPS fija; endpoints personalizados y locales se reservan a ejecución local. No se aceptan modelos `joblib` subidos por usuarios. Las exportaciones neutralizan fórmulas CSV y los errores HTTP no incluyen credenciales. No publiques `.venv`, `storage`, `data/raw`, logs, `.env` ni claves.

Una contraseña compartida no sustituye autenticación por usuario, auditoría, cuotas ni protección antiabuso. Si se expone el Chat con IA a internet, el operador también asume costes, privacidad y límites del proveedor elegido.

Las diferencias de saltos de línea Windows/Linux se controlan con `.gitattributes`: `data/movies.csv` mantiene sus bytes y el hash de procedencia y entrenamiento en Git y Render.

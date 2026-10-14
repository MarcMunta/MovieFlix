# Publicar MovieFlix en Render

Estado documental: configuración preparada. No considerar la app desplegada hasta que la URL pública responda y pase las comprobaciones finales.

Repositorio previsto: [github.com/MarcMunta/MovieFlix](https://github.com/MarcMunta/MovieFlix). No subas `data/raw`, `.venv`, `storage`, logs, `.env` ni credenciales. El build usa el catálogo normalizado y el modelo incluidos; no descarga Kaggle ni reentrena.

## Demo Free: lectura por defecto

`render.yaml` declara Python 3.13.5, plan Free, `MOVIEFLIX_MODE=cloud`, health check `/_stcore/health` y este arranque:

```text
streamlit run app.py --server.port $PORT --server.address 0.0.0.0
```

La demo Free ofrece Chat guiado, catálogo, exportación y predicción. Las altas quedan bloqueadas porque el filesystem efímero perdería cambios. No necesita ninguna API para esas funciones.

**Chat con IA no está disponible por defecto en Render Free.** La configuración predeterminada apunta a `127.0.0.1:8091`, que dentro de Render es el propio contenedor. Render no puede alcanzar llama.cpp, LM Studio u Ollama que estén en el `localhost` del ordenador del usuario. Tampoco se incluye un LLM en el servicio.

Para conectar un proveedor remoto haría falta un endpoint HTTPS accesible desde Render y su clave. La interfaz conserva esa clave solo en la sesión y nunca la guarda en disco. En la configuración Free de solo lectura, la pantalla de modelo tampoco permite cambios administrativos; se debe mantener así para una demo sin API.

## Variante persistente de pago

`render-persistent.yaml` declara plan Starter, disco de 1 GB montado en `/var/data` y:

- `MOVIEFLIX_MODE=cloud`
- `MOVIEFLIX_DATA_DIR=/var/data`
- `MOVIEFLIX_ADMIN_PASSWORD` como secreto de Render (`sync: false`)

Requiere aceptar el coste antes de crearla. Las altas se guardan en `/var/data/additions.sqlite3`; la configuración no secreta del proveedor se guarda en `/var/data/model-config.json`. La clave API introducida en la UI continúa solo en la sesión y deberá volver a introducirse tras una sesión nueva o reinicio.

El disco limita el servicio a una instancia. SQLite usa transacciones y basta para esta práctica de baja concurrencia; no es diseño de producción multiinstancia. Consulta precios y límites vigentes de [Render](https://render.com/docs/free) antes de contratar.

## Publicación

1. Publica la raíz del proyecto en el repositorio previsto.
2. En Render, crea un Blueprint desde `render.yaml` para la demo gratuita.
3. Espera estado **Live** y abre la URL `onrender.com`.
4. Verifica `https://TU-SERVICIO.onrender.com/_stcore/health`.
5. Abre Chat guiado y pregunta `¿Qué información tienes?`.
6. Busca `Inception`, abre Modelo y ejecuta una predicción.
7. Confirma que **Añadir película** informa que Render Free es de consulta.

Para la variante persistente, usa `render-persistent.yaml`, configura el secreto en Render y añade estas pruebas:

1. Autentica la edición y guarda una ficha identificada como prueba.
2. Reinicia el servicio.
3. Comprueba que la ficha sigue presente y que un duplicado título/año se rechaza.
4. Descarga el CSV completo y confirma que la alta figura como manual y su nota no aparece como IMDb.

Solo esas pruebas acreditan despliegue, WebSocket, memoria, arranque y persistencia reales. La validación local no los demuestra.

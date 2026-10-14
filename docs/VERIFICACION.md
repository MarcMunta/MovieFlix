# Verificación de MovieFlix

Fecha de revisión documental: 14/10/2026.

## Estado verificado en el código

- Dos chats independientes: Chat guiado sin API y Chat con IA configurable.
- Proveedores: OpenAI-compatible, Ollama, Anthropic y Gemini.
- Claves introducidas en la UI excluidas de la persistencia; preferencias no secretas guardadas con reemplazo atómico.
- Endpoints remotos: HTTPS y clave obligatorios; HTTP limitado a loopback.
- Plan IA validado como JSON; entre una y tres consultas de lectura.
- Snapshot SQLite en memoria, `query_only`, autorizador, funciones permitidas, límites internos, timeout de 2 segundos y máximo de 50 filas por resultado.
- Redactor IA limitado a resultados verificados; evidencia SQL visible en la interfaz.
- Borradores de alta validados, revisados y confirmados antes de guardarse.
- Altas SQLite transaccionales, título/año único y notas manuales separadas de IMDb.
- Cloud falla cerrado; Render Free queda en consulta.
- Árbol y Random Forest cargados desde el artefacto propio; no existe entrenamiento de LLM.

## Comandos de comprobación

Ejecutar desde la raíz en PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pip check
```

Resultado local sobre el estado compartido del 14/10/2026: **115 pruebas pasadas en 6,78 s**, Ruff sin hallazgos, 28 archivos con formato correcto y `pip check` sin dependencias rotas. Este resultado no sustituye una ejecución final sobre la revisión exacta que se publique.

La suite actual cubre:

- chat guiado, intención, contexto y entradas hostiles;
- motor SQL, agregados, funciones, CTE, ventanas, autorizador, truncado y presupuesto;
- formas HTTP de los cuatro proveedores, redirecciones, timeouts, errores saneados y respuesta máxima de 2 MiB;
- configuración sin clave persistida y control de edición cloud;
- validación, duplicados, concurrencia y reapertura de SQLite;
- exportación segura, separación de notas y ausencia de fuga del objetivo de entrenamiento;
- flujo Streamlit de chat, catálogo, alta, modelo y bloqueo de escritura cloud.

## Modelo clásico

El artefacto registrado contiene 19.415 ejemplos elegibles, con 11.651 en train, 3.884 en validación y 3.880 en test; grupos compartidos: 0. TF-IDF e imputación se ajustan solo sobre train.

| Modelo | Accuracy test | F1 macro |
| --- | ---: | ---: |
| Clase mayoritaria | 30,44 % | 0,0259 |
| Árbol de Decisión | 34,20 % | 0,1521 |
| Random Forest | 42,73 % | 0,1416 |

Límites: primer género listado como objetivo; clases desequilibradas; probabilidades sin calibrar; sinopsis mayoritariamente inglesas; sin evaluación específica en español; snapshot 1896–2016; altas excluidas hasta reentrenar. Random Forest obtiene más accuracy, pero el Árbol supera su F1 macro.

## Validación manual local

1. Ejecutar `.\Iniciar-MovieFlix.ps1` y abrir <http://127.0.0.1:8510>.
2. En Chat guiado, comprobar una consulta, una búsqueda y un seguimiento.
3. Sin servidor de modelo, abrir Chat con IA y comprobar que el fallo no rompe Chat guiado.
4. Con un proveedor de prueba, usar Configuración, probar conexión y hacer una pregunta agregada; revisar **Datos utilizados para responder**.
5. Preparar una alta desde chat, comprobar que aún no existe, revisar y guardar; reiniciar y comprobar persistencia.
6. Ejecutar una predicción y revisar métricas y advertencias.
7. Probar teclado, foco, sidebar y ancho móvil.

## Pendientes que no deben declararse superados sin evidencia

- URL pública de GitHub accesible con el contenido final.
- Servicio Render en estado Live, health check, arranque Linux, WebSocket y consumo de RAM.
- Chat con IA en Render: requiere endpoint remoto HTTPS; un modelo local del PC no es accesible mediante `localhost` desde la nube.
- Persistencia Render: requiere variante de pago, disco montado, secreto configurado y prueba guardar–reiniciar–recuperar.
- Auditoría completa con lector de pantalla, carga multiusuario y controles de producción como cuentas, cuotas y trazabilidad.

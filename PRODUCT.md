# MovieFlix — producto

Aplicación docente en español para estudiantes de IA/Big Data. Permite consultar el catálogo movie-flix, experimentar con preguntas guiadas o un LLM conectado por API, comparar Árbol de Decisión y Random Forest y registrar fichas manuales sin alterar el dataset original.

## Experiencia principal

- **Chat guiado:** fiable, sin modelo ni API, con sugerencias y contexto de resultados.
- **Chat con IA:** lenguaje libre con OpenAI-compatible, Ollama, Anthropic o Gemini. El modelo planea; la app valida y ejecuta SQL de lectura sobre SQLite aislado; la respuesta se basa en evidencia mostrable.
- **Catálogo y altas:** búsqueda/exportación más borradores revisados y guardado explícito en SQLite.
- **Modelo:** clasificación educativa del primer género registrado, con métricas y límites visibles.

## Reglas del producto

- Ningún chat guarda por sí solo: preparar, revisar y confirmar son pasos separados.
- Claves API solo en sesión. Preferencias no secretas persisten de forma atómica solo en local; en Render tampoco se guardan.
- La nube permite que cada usuario conecte una API propia de la lista pública permitida. Endpoints personalizados y localhost se reservan a ejecución local.
- Cloud es de solo lectura por defecto. Escribir exige disco persistente y contraseña de administración.
- MovieFlix conecta LLM existentes; no entrena uno desde cero.
- Datos ausentes, resultados truncados y límites del modelo deben mostrarse con honestidad.

## Éxito y estado

Éxito significa consultas verificables, degradación al Chat guiado cuando falla el proveedor, altas locales persistentes, modelo reproducible y UI usable. El clasificador tiene valor didáctico y precisión limitada; no debe venderse como recomendador fiable.

Repositorio público confirmado: [github.com/MarcMunta/MovieFlix](https://github.com/MarcMunta/MovieFlix). [movieflix-marcm.onrender.com](https://movieflix-marcm.onrender.com) responde al health check público con HTTP 200. La persistencia cloud de pago no se ha desplegado.

# Interfaz

Se conserva el sistema nativo de Streamlit del ejemplo: sidebar con navegación radio, contenido principal claro, formularios etiquetados, tablas nativas, componentes de chat y botones con foco/teclado. No se crea una identidad visual ajena a la práctica.

Tema: fondo blanco, superficie secundaria #F3F5F7, texto #17212B, acento #0F766E, sans serif nativa. Navegación: Chat guiado, Chat con IA, Catálogo, Añadir película, Modelo y Configuración. Las sugerencias cambian según los resultados del chat guiado; cada chat conserva su propio historial, contexto y ficha pendiente.

Concepto de pantalla: `docs/ui-concept.png`, generado con la herramienta integrada Image Gen. Implementación usa componentes nativos; el avatar y bordes dependen de Streamlit. Los tres accesos al chat se acortaron a Información, Ciencia ficción y Añadir película para evitar el truncado observado a 817 px. La indicación del modelo se precisó a «primer género registrado» por fidelidad a los datos. En móvil, sidebar colapsable y controles apilados.

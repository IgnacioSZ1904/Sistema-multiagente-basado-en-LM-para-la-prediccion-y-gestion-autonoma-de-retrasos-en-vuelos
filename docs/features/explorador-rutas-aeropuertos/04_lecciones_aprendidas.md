# Lecciones aprendidas: explorador-rutas-aeropuertos

## [2026-09-08] — El agente no puede validar visualmente la UI en este entorno Windows

**Contexto:** T4.3, intentando automatizar la validación manual en navegador (arrancar backend/frontend y comprobar con Playwright/chromium-cli) antes de pedírselo al usuario.

**Qué pasó:** `chromium-cli` no está instalado y no hay skill de proyecto para lanzar la app. Backend (`uvicorn`, puerto 8000) y frontend (`vite`, puertos 5173/5174) arrancan correctamente, pero las llamadas `curl`/`Invoke-WebRequest` desde las herramientas Bash/PowerShell del agente no siempre logran conectar a `localhost` de forma fiable (funcionó para el backend, falló de forma intermitente para el frontend). Instalar Playwright vía `npx` habría sido pesado para una validación puntual.

**Causa raíz:** El entorno del agente en esta máquina Windows no tiene un driver de navegador headless disponible ni garantías de conectividad de red consistente hacia procesos nativos de Windows lanzados desde las herramientas Bash/PowerShell del propio agente.

**Corrección aplicada:** Se paró todo lo que había arrancado el agente y se dejó la validación manual explícitamente para el usuario, marcando la tarea como bloqueada (no como completada) hasta que el usuario confirmó el resultado.

**Regla para el futuro:** En evolutivos con cambios de frontend en este proyecto, no intentar automatizar la verificación visual con Playwright/chromium-cli por defecto — comprobar primero si esas herramientas están disponibles (rápido) y, si no lo están, pasar directamente a arrancar los servidores y pedir al usuario que valide él mismo en su navegador, en lugar de invertir tiempo en instalar un driver headless para una única validación.

**Tags:** `#proceso` `#frontend` `#entorno`

## [2026-09-08] — Segunda vez consecutiva que se cierra un evolutivo sin HTML de revisión

**Contexto:** T5.1, fase de cierre.

**Qué pasó:** `docs/templates/review-template.html` sigue sin existir (ya se detectó en `prediccion-ml-real`, ver su `04_lecciones_aprendidas.md`). Se volvió a preguntar al usuario cómo proceder en vez de inventar estilos, y de nuevo se decidió omitir el HTML de revisión.

**Causa raíz:** Nadie ha creado todavía la plantilla de referencia; no es un olvido de este evolutivo en particular, es un hueco de la metodología misma que ya lleva dos evolutivos sin resolverse.

**Corrección aplicada:** Ninguna dentro de este evolutivo (fuera de alcance). Se deja anotado en `99_devlog.md` como candidato a evolutivo `meta-*`.

**Regla para el futuro:** Antes de asumir que hay que generar un HTML de revisión al cerrar cualquier evolutivo, comprobar de nuevo si `docs/templates/review-template.html` ya existe (puede haberse creado entretanto). Si sigue sin existir tras un tercer evolutivo, proponer proactivamente al usuario abrir un evolutivo `meta-crear-plantilla-review` en lugar de repetir la misma pregunta cada vez.

**Tags:** `#proceso` `#documentación`

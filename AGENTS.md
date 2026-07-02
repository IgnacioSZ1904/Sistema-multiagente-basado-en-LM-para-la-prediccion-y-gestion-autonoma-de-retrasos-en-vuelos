# AGENTS.md — Metodología de trabajo con agentes de IA

Este documento define **cómo** los agentes de IA deben colaborar en este proyecto al abordar cualquier evolutivo (nueva funcionalidad, refactor significativo, integración, etc.). El objetivo es garantizar trazabilidad, validación humana en cada paso y aprendizaje acumulado.

> **Regla de oro:** ningún agente avanza a la siguiente fase sin la aprobación explícita del responsable humano. La validación es **manual**, fichero a fichero.

---

## 1. Principios fundamentales

1. **Iteración validada**: cada fase produce un entregable (un fichero `.md`) que debe ser revisado y aprobado manualmente antes de pasar a la siguiente.
2. **Trazabilidad total**: todo lo que se hace queda registrado en ficheros versionables (Markdown), de forma que cualquier persona pueda reconstruir el razonamiento y el progreso.
3. **Aprendizaje incremental**: los errores y correcciones alimentan un fichero de lecciones aprendidas que se consulta antes de cada nueva fase.
4. **Atomicidad de tareas**: las tareas deben ser pequeñas, verificables y con un check binario (hecho / no hecho).
5. **Idempotencia documental**: si una fase se repite, se actualiza el fichero correspondiente, no se duplica.

---

## 2. Estructura de carpetas

Cada evolutivo vive en su propia carpeta, dentro de `docs/features/`:

```
docs/
├── templates/
│   └── review-template.html         # Template de referencia (componentes, estilos, formato)
└── features/
    └── <nombre-del-evolutivo>/
        ├── 01_analisis.md
        ├── 02_planificacion.md
        ├── 03_tareas_pendientes.md
        ├── 04_lecciones_aprendidas.md
        ├── 99_devlog.md
        └── <nombre-del-evolutivo>-review.html   # Generado al cerrar el evolutivo
```

### Convención de nombres

- **`<nombre-del-evolutivo>`**: `kebab-case`, breve y descriptivo. Ej.: `login-con-google`, `migracion-postgres`, `dashboard-metricas`.
- No usar fechas en el nombre de carpeta (Git ya las registra).
- Si el evolutivo es grande, dividirlo en sub-features con sus propias carpetas, no anidar dentro de una.

---

## 3. Flujo de trabajo

```
Petición del evolutivo
        ↓
[Fase 1] 01_analisis.md ──→ [Validación manual] ──→ ✅
        ↓
[Fase 2] 02_planificacion.md ──→ [Validación manual] ──→ ✅
        ↓
[Fase 3] 03_tareas_pendientes.md (se genera del plan) ──→ [Validación manual] ──→ ✅
        ↓
[Fase 4] Ejecución iterativa de tareas
        │   ├─ Marca check al completar
        │   ├─ Actualiza 99_devlog.md tras cada tarea
        │   └─ Si hay corrección/redirección → entrada en 04_lecciones_aprendidas.md
        ↓
[Fase 5] Cierre: generar <nombre>-review.html ──→ [Validación manual] ──→ ✅
        ↓
Resumen final en 99_devlog.md y consolidación de lecciones
```

### Reglas de paso entre fases

- El agente **no inicia** la fase N+1 hasta recibir confirmación explícita (ej.: `"aprobado, continúa"`, `"ok fase 2"`).
- Si tras revisar un fichero hay cambios, el agente **edita el fichero existente**, no crea uno nuevo, y vuelve a pedir validación.
- Antes de iniciar cualquier fase, el agente **lee `04_lecciones_aprendidas.md`** (si existe en éste u otros features previos) para no repetir errores.

---

## 4. Especificación de cada fichero

### 4.1 `01_analisis.md` — Análisis del estado actual y de la funcionalidad

**Propósito:** entender qué se pide, qué existe ya y qué impacto tendrá.

**Estructura obligatoria:**

```markdown
# Análisis: <nombre del evolutivo>

## 1. Petición original
> Cita literal de lo solicitado por el usuario.

## 2. Objetivo
Explicación reformulada en 2-3 frases de qué se quiere conseguir y por qué.

## 3. Estado actual del proyecto
- Módulos / ficheros relevantes existentes
- Dependencias afectadas
- Configuración actual relacionada
- Tests existentes que cubren el área

## 4. Alcance
### Dentro de alcance
- ...
### Fuera de alcance
- ...

## 5. Riesgos y dependencias
| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|--------------|---------|------------|
| ...    | ...          | ...     | ...        |

## 6. Preguntas abiertas
- [ ] ¿...?
- [ ] ¿...?

## 7. Criterios de aceptación
- [ ] Criterio medible 1
- [ ] Criterio medible 2
```

**Validación esperada del humano:** confirmar alcance, resolver preguntas abiertas, aprobar criterios de aceptación.

---

### 4.2 `02_planificacion.md` — Plan técnico detallado

**Propósito:** traducir el análisis en un plan accionable.

**Estructura obligatoria:**

```markdown
# Planificación: <nombre del evolutivo>

## 1. Enfoque técnico
Descripción de la solución propuesta a alto nivel (1-2 párrafos).

## 2. Decisiones de diseño
| Decisión | Alternativas consideradas | Justificación |
|----------|---------------------------|---------------|
| ...      | ...                       | ...           |

## 3. Cambios por módulo
### `ruta/al/modulo/`
- Qué se modifica
- Qué se añade
- Qué se elimina

## 4. Modelo de datos / contratos (si aplica)
- Esquemas, tipos, endpoints, eventos, etc.

## 5. Plan de pruebas
- Tests unitarios a añadir
- Tests de integración
- Validación manual necesaria

## 6. Plan de despliegue / migración (si aplica)
- Pasos previos
- Pasos durante
- Rollback

## 7. Estimación de complejidad
- Nº aproximado de tareas: __
- Áreas de mayor incertidumbre: __
```

**Validación esperada del humano:** aprobar enfoque técnico, decisiones de diseño y plan de pruebas.

---

### 4.3 `03_tareas_pendientes.md` — Desglose ejecutable

**Propósito:** lista exhaustiva de tareas atómicas con trazabilidad.

**Reglas:**
- Cada tarea debe ser **completable en una sesión** y **verificable**.
- Usar checkboxes Markdown (`- [ ]` / `- [x]`).
- Agrupar por bloques lógicos (preparación, implementación, pruebas, documentación).
- Las tareas se generan **a partir de** `02_planificacion.md`. Si surge una tarea no prevista, se añade aquí y se anota en `99_devlog.md`.

**Estructura:**

```markdown
# Tareas pendientes: <nombre del evolutivo>

> Estado: 🟡 En curso | 🟢 Completado | 🔴 Bloqueado
> Última actualización: <fecha>

## Bloque 1 — Preparación
- [ ] T1.1 — Crear rama `feature/<nombre>`
- [ ] T1.2 — Añadir dependencia `xxx` en `package.json`
- [ ] T1.3 — Configurar variables de entorno en `.env.example`

## Bloque 2 — Implementación
- [ ] T2.1 — Crear módulo `src/auth/google.ts` con la función `verifyToken`
- [ ] T2.2 — Integrar `verifyToken` en el middleware `authMiddleware`
- [ ] T2.3 — ...

## Bloque 3 — Pruebas
- [ ] T3.1 — Test unitario de `verifyToken` (casos: token válido, expirado, malformado)
- [ ] T3.2 — Test de integración del flujo completo de login

## Bloque 4 — Documentación
- [ ] T4.1 — Actualizar `README.md` con instrucciones de configuración
- [ ] T4.2 — Documentar nuevo endpoint en la guía de API
```

**Convenciones de marcado:**
- `- [ ]` pendiente
- `- [x]` completada
- `- [~]` en curso (opcional, útil en sesiones largas)
- `- [!]` bloqueada (añadir nota debajo explicando el bloqueo)

**Validación esperada del humano:** confirmar que el desglose cubre el plan y que las tareas son lo bastante atómicas.

---

### 4.4 `04_lecciones_aprendidas.md` — Memoria de errores y correcciones

**Propósito:** capturar cada vez que el agente se equivoca, es redirigido o descubre algo no previsto, para no repetirlo.

**Cuándo añadir una entrada:**
- El usuario corrige una decisión técnica.
- El usuario redirige el enfoque (cambio de criterio, malentendido del alcance).
- Un test falla por un motivo no contemplado.
- Se descubre una restricción del proyecto que no se conocía.
- Se incumple alguna regla de este `AGENTS.md`.

**Estructura por entrada:**

```markdown
## [YYYY-MM-DD] — Título corto de la lección

**Contexto:** qué tarea/fase se estaba ejecutando.

**Qué pasó:** descripción del error, suposición incorrecta o redirección.

**Causa raíz:** por qué ocurrió (asunción no verificada, dato no consultado, regla del proyecto desconocida...).

**Corrección aplicada:** qué se hizo para resolverlo.

**Regla para el futuro:** instrucción clara y accionable para no repetirlo.

**Tags:** `#arquitectura` `#testing` `#proceso` `#dominio` (etc.)
```

**Ejemplo:**

```markdown
## [2026-03-12] — No asumir el ORM activo

**Contexto:** Fase de planificación de `migracion-postgres`.

**Qué pasó:** Propuse usar Sequelize basándome en una mención antigua del README.

**Causa raíz:** No verifiqué el `package.json` actual antes de planificar.

**Corrección aplicada:** El proyecto migró a Prisma hace meses. Replanifiqué con Prisma.

**Regla para el futuro:** Antes de proponer cualquier librería, **leer `package.json` y `tsconfig.json` actualizados** en la fase de análisis.

**Tags:** `#proceso` `#análisis`
```

> Este fichero es **acumulativo y consultable**. Antes de iniciar cualquier fase nueva en cualquier evolutivo, el agente debe leer las lecciones aprendidas de features anteriores relevantes.

---

### 4.5 `99_devlog.md` — Bitácora incremental

**Propósito:** registro cronológico de todo lo que se va haciendo durante la ejecución.

**Reglas:**
- Una entrada **por sesión de trabajo** o **por tarea completada significativa**.
- Solo se añade al final del fichero, nunca se reescribe el pasado.
- Es el sitio donde se anotan decisiones improvisadas, dudas resueltas, comandos relevantes ejecutados.

**Estructura:**

```markdown
# Devlog: <nombre del evolutivo>

---

## [YYYY-MM-DD HH:MM] — Inicio del evolutivo
- Carpeta creada en `docs/features/<nombre>`
- Análisis iniciado

## [YYYY-MM-DD HH:MM] — Análisis aprobado
- Resueltas las preguntas abiertas 1, 2, 3
- Cambios menores en alcance: se excluye soporte para SSO empresarial

## [YYYY-MM-DD HH:MM] — Tarea T2.1 completada
- Implementada `verifyToken` en `src/auth/google.ts`
- Decisión: usar `google-auth-library` en lugar de validar manualmente el JWT
- Commit: `feat(auth): add google token verification`

## [YYYY-MM-DD HH:MM] — Bloqueo en T2.2
- El middleware actual no admite middlewares async; hace falta refactor previo
- Añadida tarea T2.2.1 para refactor; lección registrada
```

---

### 4.6 `<nombre-feature>-review.html` — Documento de revisión para compañeros

**Propósito:** servir como **punto de entrada principal** para que un compañero revise el evolutivo. Debe ser **autoexplicativo, visual y con tono comercial**, sin necesidad de abrir el resto de ficheros (que quedan como apoyo para profundizar).

**Cuándo se genera:** una vez completadas **todas** las tareas de `03_tareas_pendientes.md` y antes de dar por cerrado el evolutivo.

**Ubicación:** `docs/features/<nombre>/<nombre>-review.html`

**Template de referencia:** `docs/templates/review-template.html`

#### Reglas de uso de la template

1. **Lectura obligatoria antes de generar:** el agente debe leer `docs/templates/review-template.html` para conocer los componentes, clases CSS, paleta de colores, tipografía y estructura disponibles.
2. **No reinventar estilos:** únicamente se usan los componentes y clases que ofrece la template. Si falta un componente, se anota en `99_devlog.md` como propuesta de mejora de la template (no se inventa CSS inline).
3. **Theme light obligatorio:** el documento siempre se entrega en tema claro, con tono profesional / comercial (apto para compartir con stakeholders no técnicos).
4. **Autocontenido:** CSS y JS deben quedar embebidos o referenciados con rutas relativas que funcionen al abrir el fichero directamente en el navegador.

#### Contenido obligatorio

El HTML debe estructurarse con las siguientes secciones (usando los componentes equivalentes de la template):

| Sección | Propósito | Origen de la información |
|---------|-----------|--------------------------|
| **Header / Hero** | Nombre del evolutivo, fecha, autor (agente + revisor humano), estado | Metadatos del feature |
| **Resumen ejecutivo** | 3-5 frases que cualquier persona del negocio entendería | Reformulación de `01_analisis.md` §2 |
| **¿Qué aporta?** | Beneficios y casos de uso principales | `01_analisis.md` §2 y §4 |
| **¿Cómo funciona?** | Explicación funcional paso a paso, con diagramas o capturas si la template los soporta | `02_planificacion.md` §1 |
| **Cambios técnicos** | Resumen de qué se ha tocado en el código, organizado por módulo | `02_planificacion.md` §3 y devlog |
| **Decisiones de diseño relevantes** | Las 2-3 decisiones más importantes y su justificación | `02_planificacion.md` §2 |
| **Cómo probarlo** | Pasos concretos para que el revisor verifique la funcionalidad | `01_analisis.md` §7 + plan de pruebas |
| **Riesgos conocidos y limitaciones** | Lo que el revisor debe vigilar | `01_analisis.md` §5 |
| **Enlaces a documentación de apoyo** | Links relativos a los `.md` del feature | Ficheros del propio directorio |

#### Tono y estilo

- **Comercial pero honesto:** vende los beneficios sin ocultar limitaciones.
- **Cero jerga innecesaria:** si se usa un término técnico, se explica brevemente la primera vez.
- **Visual:** preferir tablas, badges, callouts y diagramas frente a párrafos largos, **siempre que la template los ofrezca**.
- **Trazabilidad:** cada afirmación importante debe poder rastrearse a uno de los ficheros `.md` del feature.

#### Validación del humano

El revisor humano valida que:
- El HTML renderiza correctamente en navegador.
- El contenido es fiel a lo implementado (no promete cosas no hechas).
- El tono es adecuado para compartir con el compañero revisor.
- Los enlaces a documentación de apoyo funcionan.

Si tras la validación el revisor pide cambios, el agente **edita el HTML existente**, registra la corrección en `99_devlog.md` y, si aplica, en `04_lecciones_aprendidas.md` (por ejemplo, si la lección es sobre cómo comunicar mejor).

---

## 5. Protocolo del agente al recibir una petición

Cuando el usuario solicita un nuevo evolutivo, el agente:

1. **Confirma el nombre en kebab-case** y el alcance general en una sola frase.
2. **Crea la carpeta** `docs/features/<nombre>/` con los 5 ficheros vacíos (o solo la plantilla del que toca según la fase).
3. **Lee `04_lecciones_aprendidas.md`** de features anteriores relevantes.
4. **Redacta `01_analisis.md`** siguiendo la plantilla y se detiene.
5. **Pide validación explícita** antes de continuar.
6. Tras la aprobación, repite el ciclo para la siguiente fase.
7. **Al completar todas las tareas**, lee `docs/templates/review-template.html` y genera `<nombre>-review.html` en la carpeta del feature. Pide validación final.

### Plantilla de mensaje al cerrar cada fase

```
He completado [fase].
📄 Fichero: docs/features/<nombre>/0X_<nombre>.md

Resumen:
- ...
- ...

⏸️ Espero tu validación para continuar.
```

---

## 6. Reglas durante la ejecución de tareas

- **Una tarea a la vez** salvo que el usuario indique lo contrario.
- Al completar una tarea:
  1. Marcar `- [x]` en `03_tareas_pendientes.md`.
  2. Añadir entrada en `99_devlog.md`.
  3. Si hubo corrección o aprendizaje, añadir en `04_lecciones_aprendidas.md`.
- **No marcar como hecha** una tarea cuyos tests no pasen o cuya verificación no se haya ejecutado.
- Si una tarea revela trabajo no previsto, **añadirla** a `03_tareas_pendientes.md` con un identificador derivado (T2.2.1, T2.2.2…) en lugar de inflar la tarea original.

---

## 7. Reglas anti-deriva (qué NO hacer)

- ❌ No saltarse fases aunque la tarea parezca trivial.
- ❌ No reescribir el devlog: solo se añade al final.
- ❌ No fusionar análisis y planificación en un mismo fichero.
- ❌ No marcar tareas como hechas sin evidencia (test, ejecución, revisión).
- ❌ No tomar decisiones de diseño durante la ejecución sin reflejarlas en el devlog.
- ❌ No asumir contexto: si algo no está claro, preguntar antes de avanzar.
- ❌ No generar el HTML de revisión con estilos inventados: usar siempre los componentes de `docs/templates/review-template.html`.
- ❌ No dar por cerrado el evolutivo sin el HTML de revisión validado.

---

## 8. Ejemplo completo: ciclo de un evolutivo

**Petición del usuario:** *"Quiero añadir login con Google a la app."*

```
1. Agente: "Voy a llamarlo `login-con-google`. ¿Confirmas?"
2. Usuario: "Sí."
3. Agente crea docs/features/login-con-google/ con los 5 ficheros.
4. Agente lee 04_lecciones_aprendidas.md de otras features.
5. Agente rellena 01_analisis.md y pide validación.
6. Usuario: "Cambia el criterio de aceptación 3, lo demás OK."
7. Agente edita 01_analisis.md y añade entrada en 04_lecciones_aprendidas.md
   (lección: aclarar criterios medibles antes de cerrarlos).
8. Usuario: "Ahora sí, continúa."
9. Agente rellena 02_planificacion.md y pide validación. ✅
10. Agente rellena 03_tareas_pendientes.md y pide validación. ✅
11. Agente ejecuta T1.1, marca check, escribe en 99_devlog.md.
12. Agente ejecuta T1.2... y así sucesivamente.
13. Al completar todas las tareas, el agente lee docs/templates/review-template.html
    y genera login-con-google-review.html en la carpeta del feature.
14. Usuario revisa el HTML en el navegador y valida.
15. Resumen final en 99_devlog.md y cierre del evolutivo.
```

---

## 9. Mantenimiento de esta metodología

Si durante el uso de esta metodología surge una mejora del proceso en sí, se propone como un evolutivo más con nombre `meta-<algo>` (ej.: `meta-anadir-fase-revision-seguridad`) y se sigue el mismo flujo. Las modificaciones a este `AGENTS.md` requieren validación humana explícita.

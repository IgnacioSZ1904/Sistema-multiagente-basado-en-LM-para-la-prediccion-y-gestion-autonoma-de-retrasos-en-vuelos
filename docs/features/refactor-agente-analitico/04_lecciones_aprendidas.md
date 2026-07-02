# Lecciones aprendidas: refactor-agente-analitico

## [2026-07-02] — El usuario redirigió la propiedad de la predicción tras validar la planificación

**Contexto:** Fase 2 (`02_planificacion.md`) ya redactada y compartida para validación. La respuesta del usuario a la pregunta 6.1 de `01_analisis.md` ("Lo confirmo...") se había interpretado como: la responsabilidad de predecir (`is_disruption`/`confidence`/`main_cause`) se traslada del agente analítico al agente de disrupción, ya que este último "no accede a la base de datos" y por tanto necesita recibir esa información ya elaborada.

**Qué pasó:** Tras leer la planificación completa, el usuario se retractó: quiere que el **agente analítico siga haciendo las predicciones**. Lo que realmente pedía con "no accede a la BD" era que la comunicación entre agentes fuera JSON estructurado (estilo MCP) para hacerla más eficiente y explícita — no que la responsabilidad de predecir cambiara de agente.

**Causa raíz:** Se sobre-interpretó una respuesta breve del usuario ("Lo confirmo... que no accederá a la base de datos") como una redefinición completa de qué agente calcula qué, cuando en realidad la frase clave era sobre el **mecanismo de comunicación** (JSON explícito entre agentes), no sobre **quién razona sobre los datos**. No se verificó explícitamente con el usuario antes de invertir una fase completa de planificación en el supuesto más amplio.

**Corrección aplicada:** Se revirtió el diseño: `analytical_agent` conserva `delay_prediction`, pero su cálculo pasa a ser determinista en código (no LLM), preservando JSON puro sin narrativa y sin coste de latencia extra. `disruption_agent` vuelve a limitarse a "gestionar" (severidad/acciones), consumiendo `delay_prediction` ya calculado. Se generalizó el principio de "JSON explícito entre agentes" (serialización `json.dumps` en vez de interpolar `repr()` de dicts) a `disruption_agent` y `communication_agent`, que es lo que realmente pedía el usuario con la referencia a MCP.

**Regla para el futuro:** Cuando una respuesta del usuario a una pregunta abierta usa una frase que podría interpretarse de varias formas con distinto alcance (aquí: "no accede a la BD" podía significar "cambia de agente quién calcula X" o "cambia cómo se comunican los agentes"), y la interpretación elegida tiene un impacto arquitectónico grande (mover responsabilidad de predicción entre agentes), conviene **resumir la interpretación en una frase antes de desarrollarla en detalle** y solo entonces escribir el plan completo — no asumir el alcance más amplio posible y descubrir el desacuerdo al final de una fase entera.

**Tags:** `#arquitectura` `#proceso` `#requisitos`

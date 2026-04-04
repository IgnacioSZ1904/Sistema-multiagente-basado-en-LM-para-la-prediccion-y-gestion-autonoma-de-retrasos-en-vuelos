Sistema Multiagente para la Gestión Autónoma de Retrasos en el Tráfico Aéreo
📌 Descripción del Proyecto

Este repositorio contiene el código fuente del Trabajo de Fin de Grado (TFG) centrado en el diseño y desarrollo de un sistema multiagente basado en Modelos de Lenguaje (LM). El objetivo principal es mitigar el impacto operativo de los retrasos aéreos, un problema crítico que genera un efecto dominó en la red aeroportuaria.

El sistema analiza situaciones operativas, anticipa disrupciones y propone respuestas de forma autónoma, utilizando como base de conocimiento un dataset real de vuelos comerciales en Estados Unidos.

🧠 Arquitectura del Sistema Multiagente

El núcleo de la solución se compone de una red de agentes inteligentes especializados y coordinados:

Agente Orquestador: Coordina la comunicación, distribuye tareas según el contexto operativo y sintetiza las respuestas finales.

Agente Analítico: Procesa datos históricos y en tiempo real para detectar patrones, identificar rutas problemáticas y predecir el efecto en cadena de los retrasos.

Agente de Gestión de Disrupciones: Razona sobre las opciones ante un retraso detectado y propone soluciones concretas, como la reasignación de pasajeros o la priorización de recursos.

Agente de Comunicación: Traduce las decisiones operativas a lenguaje natural para generar notificaciones a operadores y pasajeros afectados.

⚙️ Funcionalidades Principales

Análisis exploratorio automatizado de causas, aeropuertos y rutas con alta incidencia de retrasos

Predicción de retrasos en tiempo real y estimación de su impacto sobre las operaciones conectadas.

Generación autónoma de planes de actuación minimizando el coste operativo y los pasajeros afectados.

Interfaz conversacional para la interacción fluida con operadores en lenguaje natural.

Panel de visualización (Dashboard) para la monitorización de vuelos en riesgo, decisiones del sistema y métricas de rendimiento.

🛠️ Stack Tecnológico

Lenguaje principal: Python

Frameworks de Agentes: LangChain o CrewAI.

Análisis y Procesamiento de Datos: Pandas, NumPy, Scikit-learn, Spark.

Backend & Frontend: FastAPI, React.

Base de Datos: MySQL.

🔄 Metodología

El desarrollo sigue una metodología incremental iterativa basada en principios ágiles, estructurada en Sprints de 1 a 2 semanas. Este enfoque permite un ajuste continuo del comportamiento no determinista de los modelos de lenguaje y facilita la integración progresiva de cada agente en el sistema global.

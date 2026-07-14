# Anymotor — Sistema Multiagente de Venta de Autos Usados

## Descripción
Sistema multiagente en Python que automatiza el flipping de autos usados en Lima, Perú: detecta autos baratos en Facebook Marketplace, evalúa con IA si conviene comprarlos para revender con ganancia, genera el anuncio de reventa, atiende a los clientes potenciales y cierra la negociación. Construido sobre **LangChain + LangGraph**, con Streamlit como interfaz web y un bot de Telegram como interfaz conversacional alternativa.

## Tecnologías
- Python 3.12
- **LangChain** + **LangGraph** (StateGraph, checkpointing, agente ReAct)
- **Groq** (ChatGroq, modelo llama-3.3-70b-versatile; visión con llama-4-scout)
- **LangSmith** (observabilidad, tracing y monitoreo por entorno)
- Streamlit (interfaz web) + python-telegram (bot conversacional)
- Pydantic (estado del grafo y schemas de salida estructurada)
- Playwright (scraping de Facebook Marketplace)
- Airtable (CRM), CallMeBot (alertas WhatsApp), fpdf2 (contratos PDF)
- pytest + pytest-asyncio (tests con mocks de LLM)
- Docker (contenedorización)
- GitHub Actions (CI/CD)

## Arquitectura

El pipeline adquisición → publicación es un `StateGraph` de LangGraph con ramificación condicional. CRM y Cierre se invocan por turno porque dependen de entradas humanas.

| Agente | Rol | Tipo |
|--------|-----|------|
| AcquisitionAgent | Tasación y decisión de compra | Nodo del grafo |
| PublicationAgent | Generación de anuncio de reventa | Nodo del grafo |
| CRMChatbotAgent | Atención al cliente con memoria persistida | StateGraph propio |
| SalesClosingAgent | Negociación y cierre de venta | Invocado por turno |
| TelegramBotAgent | Interfaz conversacional (agente ReAct + 5 tools) | Independiente |

Estado compartido: `CarSaleState` (Pydantic) + checkpointing con `AsyncSqliteSaver`.

## Observabilidad — LangSmith

3 proyectos separados por entorno:

| Entorno | Proyecto LangSmith | Propósito |
|---------|-------------------|-----------|
| Desarrollo | `anymotor-dev` | Trazas de uso local/interactivo |
| Staging | `anymotor-staging` | Evaluación golden set en CI (develop) |
| Producción | `anymotor-prod` | Evaluación golden set en CI (main) |

Se monitorean: trazas, llamadas LLM, latencia (P50/P99), tokens, costos y tasa de error.

## Monitoreo y alertas

| Módulo | Descripción |
|--------|-------------|
| `trace_logger.py` | Consulta trazas de LangSmith para dashboarding |
| `cost_tracker.py` | Tracking de costos por agente, alertas de presupuesto ($50/mes) |
| `finops.py` | Reportes mensuales y tendencia diaria de costos |
| `alerts.py` | Alertas de latencia (P99 > 15s), error rate (> 50%), costo (90%/100%) |
| `security_logger.py` | Detección de prompt injection (11 patrones regex) |
| `incident_manager.py` | Gestión de incidentes (detected → triaging → resolved → postmortem) |

## Evaluación — Golden Set

10 casos de prueba con entradas y salidas esperadas (`evaluation/golden_set.py`).

| Métrica | Umbral | Definición |
|---------|--------|------------|
| Exactitud | ≥ 90% | % de decisiones correctas (apto_venta) |
| Groundedness | ≥ 95% | Precio estimado dentro del rango esperado |
| Latencia P95 | < 3000 ms | Tiempo extremo a extremo |
| Costo/consulta | < $0.01 | Tokens × tarifa del modelo |

La evaluación se ejecuta automáticamente en el pipeline CI/CD en cada push a `main`.

## CI/CD — GitHub Actions

Pipeline con 5 jobs:

```
Lint (Ruff) → Unit Tests → Golden Set Validation (dry-run)
                         → Docker Build Check
                         → Golden Set Evaluation (LLM) [solo main]
```

| Entorno | Rama | Secrets |
|---------|------|---------|
| `development` | develop | LANGSMITH_API_KEY |
| `testing` | main (lint/test/docker) | LANGSMITH_API_KEY |
| `production` | main (evaluate-llm) | GROQ_API_KEY, LANGSMITH_API_KEY |

## Seguridad

- Secrets en variables de entorno (`.env` local, GitHub Secrets en CI)
- Detección de prompt injection con 11 patrones regex
- Alertas automáticas al detectar inyección
- Validación de salida estructurada vía Pydantic

## Instalación
1. Instalar Python 3.12+ y crear un entorno virtual.
2. Instalar dependencias:
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```
3. Configurar variables de entorno (copiar `.env.example` a `.env`):
   - `GROQ_API_KEY` — obligatorio (gratis en console.groq.com)
   - `APP_USER` y `APP_PASSWORD` — login de la app
   - `LANGSMITH_API_KEY`, `LANGSMITH_TRACING=true`, `LANGSMITH_PROJECT` — para observabilidad
   - Airtable, Telegram, WhatsApp — opcional

## Ejecución
```bash
streamlit run app.py
```
Abre en `http://localhost:8501`.

## Tests
```bash
python -m pytest tests/ -v --tb=short
```
36 tests con mocks de LLM — no gastan tokens ni requieren API key real.

## Estructura del proyecto
```
├── agents/              # Agentes especializados + orquestador
├── tools/               # Scraper, Airtable, PDF, Telegram, WhatsApp
├── shared/              # Estado compartido, checkpointing, eventos
├── monitoring/          # Trazas, costos, alertas, seguridad, incidentes
├── evaluation/          # Golden set, métricas, runner
├── tests/               # Suite pytest (36 tests)
├── .github/workflows/   # Pipeline CI/CD
├── Dockerfile
├── requirements.txt
└── app.py               # Interfaz Streamlit
```

## Trabajo futuro
- Human-in-the-loop: pausar el grafo para aprobación humana antes de publicar
- PII masking: enmascarar datos personales antes de enviar al LLM
- LLM-as-judge: evaluadores que usen un LLM para juzgar calidad de respuestas
- Online evals: evaluación sobre tráfico real en producción
- Feedback del usuario: thumbs up/down en la UI
- Semantic cache: reutilizar respuestas LLM para consultas similares
- Rate limiting por usuario/sesión
- Deploy automático a servidor de producción

---
*Proyecto: Automatización Inteligente de Procesos — UPAO 2026-10*

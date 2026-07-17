"""Anymotor Telegram Bot Agent — agente ReAct de LangGraph con memoria persistida."""

from __future__ import annotations

import asyncio
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Literal

import requests
from langchain.agents import create_agent

# Avoid UnicodeEncodeError on Windows consoles stuck on a legacy codepage (cp1252)
# when logging Spanish text (tildes, emoji) to stdout. Also force line buffering:
# stdout is block-buffered when redirected to a file/pipe (not a TTY), so without
# this, log lines sit unflushed until enough of them pile up — making the bot
# look "silent" even while it's alive and long-polling normally.
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langchain_groq import ChatGroq
from langgraph.checkpoint.base import BaseCheckpointSaver
from pydantic import BaseModel, Field

from agents.crm_chatbot_agent import CRMChatbotAgent
from agents.orchestrator import Orchestrator
from agents.sales_closing_agent import SalesClosingAgent
from shared.checkpointing import checkpointer_scope
from shared.graph_state import CarSaleState
from shared.listings_store import get_listing
from tools.airtable_tool import AirtableTool
from tools.seen_listings import is_seen, mark_seen

BOT_MODEL = "llama-3.3-70b-versatile"
_PIPELINE_STATES = ("Encontrado", "Contactando", "Negociando", "Comprado", "Vendido")


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[AnyBot {ts}] {msg}", flush=True)


SYSTEM_PROMPT = """Eres el agente inteligente de Anymotor, una herramienta de flipping de autos usados en Perú.
Ayudas al usuario a encontrar, analizar y gestionar autos para comprar y revender con ganancia.

CAPACIDADES:
- buscar_autos: busca y analiza autos en Facebook Marketplace (Lima, Trujillo, Arequipa)
- ver_pipeline: muestra los autos guardados por estado en la base de datos
- analizar_url: analiza un listing específico de Facebook Marketplace por URL
- actualizar_estado: cambia el estado de un deal en la base de datos
- resumen: estadísticas de ganancias y pipeline

CONTEXTO DEL MERCADO PERUANO:
- Tipo de cambio: S/3.75 = $1 USD
- Margen mínimo rentable: 18-20% sobre el precio de compra
- Sweet spot Lima: $4,000-$15,000
- Mejores modelos para flip: Toyota Yaris, Corolla, Hyundai Accent, Kia Rio, Suzuki Swift

REGLAS CRÍTICAS — DEBES SEGUIRLAS SIEMPRE:

1. CANTIDAD: `cantidad` = número de autos a analizar (1-5 máximo absoluto).
   - "busca 1 Hilux" → cantidad=1
   - "busca 3 autos" → cantidad=3
   - "busca 20 autos" → cantidad=5, informa al usuario del límite

2. PRECIO — regla más importante:
   - Si el usuario pide un MODELO ESPECÍFICO y NO menciona precio → omite precio_min y precio_max (deja en 0 = sin filtro). Ejemplo: "busca una Hilux en Trujillo" → precio_min=0, precio_max=0
   - Si el usuario busca SIN modelo específico → usa precio_min=3000, precio_max=15000
   - Si el usuario menciona un rango explícito ("menos de 10000", "entre 5k y 8k") → úsalo exactamente
   - Modelos caros que SIEMPRE van sin filtro de precio: Hilux, Land Cruiser, RAV4, Fortuner, Ranger, Frontier, L200, Outlander, Tucson, Sportage (pueden costar $15,000-$40,000)

3. NUNCA llames buscar_autos más de UNA vez por mensaje. Si ya buscaste, responde con lo que encontraste.

4. Si buscar_autos no encuentra resultados → responde al usuario directamente. NO busques de nuevo con otros parámetros.

4b. Si el usuario pide "lista los resultados", "muéstrame lo que encontraste" o similar → los resultados ya están en el historial de conversación anterior. NO vuelvas a llamar buscar_autos. Responde usando el historial.

5b. Cuando el usuario diga "acepta", "acepta todas", "acepta las oportunidades" → usa actualizar_estado con nuevo_estado="Contactando" para CADA auto encontrado. El titulo_parcial debe ser una parte EXACTA del título que apareció en los resultados anteriores (cópialo del historial). Puedes llamar actualizar_estado múltiples veces seguidas, una por auto.

5. Cuando el usuario pegue una URL de Facebook Marketplace → usa analizar_url.
6. Cuando pregunte por sus autos, pipeline o negociaciones → usa ver_pipeline UNA VEZ. Su resultado se envía directamente al usuario; no repitas la llamada.
7. Cuando pregunte por estadísticas o ganancias → usa resumen UNA VEZ. Su resultado se envía directamente al usuario; no repitas la llamada.
8. NUNCA encadenes varias herramientas en la misma respuesta a menos que el usuario lo pida explícitamente.
8b. Si el usuario pregunta por un auto ESPECÍFICO del pipeline que ya se mostró ("cuánto vale el Nissan Sentra", "dime más del Ford Explorer") → usa la información del historial de conversación para responder. NO llames ver_pipeline de nuevo.
9. Responde siempre en español, directo y conciso.
10. Usa emojis con moderación."""


class BuscarAutosArgs(BaseModel):
    ciudad: Literal["lima", "trujillo", "arequipa"] = Field(
        description="Ciudad peruana donde buscar"
    )
    modelo: str = Field(
        default="",
        description="Modelo a buscar (ej: 'Toyota Corolla'). Vacío = cualquier auto.",
    )
    precio_min: int = Field(
        default=0,
        description=(
            "Precio mínimo en USD. USA 0 para buscar sin límite mínimo. Omite o usa 0 cuando el "
            "usuario pide un modelo específico sin mencionar precio."
        ),
    )
    precio_max: int = Field(
        default=0,
        description=(
            "Precio máximo en USD. USA 0 para buscar sin límite máximo. Omite o usa 0 cuando el "
            "usuario pide un modelo específico sin mencionar precio. Modelos caros (Hilux, RAV4, "
            "SUVs) suelen costar más de $15,000 — no les pongas límite."
        ),
    )
    cantidad: int = Field(default=3, description="Autos a analizar, 1-5 (defecto: 3)")


class VerPipelineArgs(BaseModel):
    estado: Literal[
        "todos", "Encontrado", "Contactando", "Negociando", "Comprado", "Vendido"
    ] = Field(default="todos", description="Estado a filtrar. 'todos' para ver todos.")


class AnalizarUrlArgs(BaseModel):
    url: str = Field(description="URL completa del listing de Facebook Marketplace")


class ActualizarEstadoArgs(BaseModel):
    titulo_parcial: str = Field(
        description="Parte del título del auto para identificarlo (ej: 'Corolla 2018')"
    )
    nuevo_estado: Literal[
        "Encontrado", "Contactando", "Negociando", "Comprado", "Vendido"
    ] = Field(description="Nuevo estado del pipeline")


class ResumenArgs(BaseModel):
    pass


class TelegramBotAgent:
    """Bot de Telegram (long-polling) respaldado por un agente ReAct de LangGraph."""

    def __init__(
        self,
        token: str,
        groq_key: str,
        allowed_users: list[str] | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
    ) -> None:
        self.token = token
        self.groq_key = groq_key
        self.allowed_users = [
            str(u).strip() for u in (allowed_users or []) if str(u).strip()
        ]
        self.airtable = AirtableTool()
        self.model = ChatGroq(model=BOT_MODEL, api_key=groq_key, temperature=0.25)
        self._checkpointer_override = checkpointer
        self._offset = 0
        self._running = False
        # Negociaciones activas de clientes potenciales (no-owner), por chat_id.
        # En memoria del proceso: alcanza para una sesión de demo/uso normal.
        self._customer_states: dict[int, CarSaleState] = {}
        # Última contraoferta enviada por chat_id — permite reconocer un
        # "acepto" en lenguaje natural (sin número) como esa misma oferta.
        self._last_counteroffer: dict[int, float] = {}
        # chat_id -> {"offer": float, "step": str, "datos": dict} mientras se
        # recolectan nombre/DNI/correo/fecha de cita antes de cerrar de verdad.
        self._pending_close: dict[int, dict] = {}

    # ── Telegram API helpers ──────────────────────────────────────────────────

    def _post(self, method: str, **payload) -> dict:
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{self.token}/{method}",
                json=payload,
                timeout=10,
            )
            return r.json()
        except Exception:
            return {}

    def send_message(self, chat_id: int, text: str) -> None:
        for chunk in _split_text(text, 4000):
            self._post(
                "sendMessage", chat_id=chat_id, text=chunk, parse_mode="Markdown"
            )

    def _typing(self, chat_id: int) -> None:
        self._post("sendChatAction", chat_id=chat_id, action="typing")

    def _get_updates(self) -> list[dict]:
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{self.token}/getUpdates",
                params={"offset": self._offset, "timeout": 25},
                timeout=30,
            )
            if r.status_code == 200:
                return r.json().get("result", [])
        except Exception:
            pass
        return []

    # ── Auth ──────────────────────────────────────────────────────────────────

    def _is_authorized(self, user_id: int) -> bool:
        if not self.allowed_users:
            return False
        return str(user_id) in self.allowed_users

    # ── Main polling loop ─────────────────────────────────────────────────────

    def run_forever(self) -> None:
        self._running = True
        print(
            f"[AnyBot] Iniciado. Usuarios autorizados: {self.allowed_users or 'ninguno'}",
            flush=True,
        )
        while self._running:
            try:
                for upd in self._get_updates():
                    self._offset = upd["update_id"] + 1
                    self._dispatch(upd)
            except Exception as e:
                print(f"[AnyBot] Error en polling: {e}")
                time.sleep(5)

    def _dispatch(self, update: dict) -> None:
        msg = update.get("message") or update.get("edited_message")
        if not msg or not msg.get("text"):
            return
        chat_id = msg["chat"]["id"]
        user_id = msg["from"]["id"]
        username = (
            msg["from"].get("username") or msg["from"].get("first_name") or str(user_id)
        )
        text = msg["text"].strip()
        _log(f"MSG  [{username}] → {text[:120]}")
        threading.Thread(
            target=self._handle, args=(chat_id, user_id, username, text), daemon=True
        ).start()

    # ── Message handler ───────────────────────────────────────────────────────

    def _handle(self, chat_id: int, user_id: int, username: str, text: str) -> None:
        if not self._is_authorized(user_id):
            self._handle_customer(chat_id, username, text)
            return

        if text == "/start":
            _log(f"CMD  [{username}] /start")
            self.send_message(
                chat_id,
                (
                    "👋 *¡Hola! Soy el agente de Anymotor.*\n\n"
                    "Puedo ayudarte a:\n"
                    "• 🔍 Buscar autos en Lima, Trujillo o Arequipa\n"
                    "• 📋 Ver tu pipeline de deals\n"
                    "• 🔗 Analizar un auto (pega la URL de Facebook)\n"
                    "• ✏️ Actualizar el estado de un deal\n"
                    "• 📊 Ver tu resumen de ganancias\n\n"
                    "Escríbeme lo que necesitas en lenguaje normal. ¿Qué buscamos hoy?"
                ),
            )
            return

        if text == "/reset":
            _log(f"CMD  [{username}] /reset")
            asyncio.run(self._reset_thread(str(chat_id)))
            self.send_message(chat_id, "✅ Conversación reiniciada.")
            return

        if text == "/id":
            self.send_message(chat_id, f"Tu Telegram ID es: `{user_id}`")
            return

        self._typing(chat_id)
        response = asyncio.run(self._run_agent(chat_id, username, text))
        _log(f"RESP [{username}] ← {response[:120].replace(chr(10), ' ')}")
        self.send_message(chat_id, response)

    # ── Flujo de clientes potenciales (no-owner) ──────────────────────────────
    # Un cliente llega acá tocando el botón "Consultar y negociar" del anuncio
    # publicado en el canal (deep link /start neg_<car_id>). A partir de ahí
    # conversa con CRMChatbotAgent y, si menciona una oferta numérica, se
    # negocia el cierre con SalesClosingAgent — el mismo par de agentes que
    # usa la pestaña "CRM y Cierre" de la app web, pero disparado desde Telegram.

    def _handle_customer(self, chat_id: int, username: str, text: str) -> None:
        start_match = re.match(r"^/start\s+neg_(.+)$", text.strip())
        if start_match:
            car_id = start_match.group(1).strip()
            car_data = get_listing(car_id)
            if not car_data:
                _log(f"CUST [{username}] /start con car_id desconocido: {car_id}")
                self.send_message(
                    chat_id,
                    "No encontré ese anuncio — puede que ya no esté disponible.",
                )
                return
            self._customer_states[chat_id] = CarSaleState(
                car_id=car_id, car_data=car_data
            )
            self._last_counteroffer.pop(chat_id, None)
            self._pending_close.pop(chat_id, None)
            titulo = (
                f"{car_data.get('marca', '')} {car_data.get('modelo', '')} "
                f"{car_data.get('año', '')}"
            ).strip()
            _log(f"CUST [{username}] inicia consulta por auto {car_id}")
            self.send_message(
                chat_id,
                f"👋 ¡Hola! Estás consultando por: *{titulo}*.\n\n"
                "Preguntame lo que quieras sobre el auto, o directamente hacime tu oferta "
                "(ej. *\"te ofrezco 8000\"*) y negociamos al toque 🙂",
            )
            return

        state = self._customer_states.get(chat_id)
        if state is None:
            self.send_message(
                chat_id,
                "🔒 No tengo el contexto de qué auto te interesa.\n"
                'Usá el botón "💬 Consultar y negociar" del anuncio en nuestro canal '
                "de Telegram para empezar la conversación.",
            )
            return

        self._typing(chat_id)
        asyncio.run(self._run_customer_turn(chat_id, username, text, state))

    async def _run_customer_turn(
        self, chat_id: int, username: str, text: str, state: CarSaleState
    ) -> None:
        # Ya se aceptó un precio y estamos juntando nombre/DNI/correo/fecha
        # antes de cerrar de verdad -> este mensaje es la respuesta al dato
        # pendiente, no pasa por CRM ni por _extract_offer.
        if chat_id in self._pending_close:
            await self._advance_closing(chat_id, username, text, state)
            return

        crm = CRMChatbotAgent(api_key=self.groq_key)
        try:
            crm_result = await crm.handle_message(text, state)
        except Exception as e:
            _log(f"CUST ERR [{username}] CRM: {e}")
            self.send_message(chat_id, f"⚠️ Error al procesar tu mensaje: {e}")
            return

        oferta = _extract_offer(text)
        if oferta is None and _is_acceptance(text):
            # "Acepto" / "de acuerdo" sin número -> asumimos que acepta la
            # última contraoferta que le hicimos (si hay una pendiente).
            oferta = self._last_counteroffer.get(chat_id)

        if oferta is None:
            self.send_message(
                chat_id, crm_result.get("respuesta_cliente", "¿Podés contarme más?")
            )
            return

        closing = SalesClosingAgent(api_key=self.groq_key)
        try:
            result = await closing.negotiate(offer=oferta, state=state)
        except Exception as e:
            _log(f"CUST ERR [{username}] Cierre: {e}")
            self.send_message(chat_id, f"⚠️ Error al negociar: {e}")
            return

        self._send_closing_result(chat_id, username, oferta, result, state)

    async def _advance_closing(
        self, chat_id: int, username: str, text: str, state: CarSaleState
    ) -> None:
        pending = self._pending_close[chat_id]
        step = pending["step"]
        valid, value_or_msg = _validate_closing_field(step, text)
        if not valid:
            self.send_message(chat_id, value_or_msg)
            return

        pending["datos"][step] = value_or_msg
        next_step = _next_closing_step(step)

        if next_step is not None:
            pending["step"] = next_step
            self.send_message(chat_id, _CLOSING_PROMPTS[next_step])
            return

        # Se juntaron los 4 datos -> cerrar de verdad.
        oferta = pending["offer"]
        datos = pending["datos"]
        fecha_cita = datos.pop("fecha", "")
        self._pending_close.pop(chat_id, None)

        closing = SalesClosingAgent(api_key=self.groq_key)
        try:
            result = await closing.negotiate(
                offer=oferta, state=state, fecha_cita=fecha_cita, datos_comprador=datos
            )
        except Exception as e:
            _log(f"CUST ERR [{username}] Cierre: {e}")
            self.send_message(chat_id, f"⚠️ Error al negociar: {e}")
            return
        self._send_closing_result(chat_id, username, oferta, result, state)

    def _send_closing_result(
        self,
        chat_id: int,
        username: str,
        oferta: float,
        result: dict,
        state: CarSaleState,
    ) -> None:
        if result.get("requiere_datos_cierre"):
            _log(f"CUST [{username}] oferta ${oferta:,.0f} aceptada, pide datos de cierre")
            self._pending_close[chat_id] = {"offer": oferta, "step": "nombre", "datos": {}}
            self._last_counteroffer.pop(chat_id, None)
            mensaje = result.get("mensaje_cliente", "")
            self.send_message(chat_id, f"{mensaje}\n\n{_CLOSING_PROMPTS['nombre']}")
            return

        if result.get("venta_completada"):
            _log(f"CUST [{username}] venta cerrada en ${result['precio_final']:,.0f}")
            self._last_counteroffer.pop(chat_id, None)
            self.send_message(
                chat_id,
                f"🎉 {result.get('mensaje_cliente', '')}\n\n"
                f"Precio final acordado: *${result['precio_final']:,.0f}*. "
                "¡Nos ponemos en contacto para coordinar la entrega!",
            )
            pdf_path = state.sale_data.get("contrato_pdf")
            if pdf_path and Path(pdf_path).exists():
                self._send_document(chat_id, pdf_path)
        else:
            if result.get("contraoferta") is not None:
                self._last_counteroffer[chat_id] = result["contraoferta"]
            _log(
                f"CUST [{username}] oferta ${oferta:,.0f} rechazada, "
                f"contraoferta ${result.get('contraoferta', 0):,.0f}"
            )
            self.send_message(
                chat_id, result.get("mensaje_cliente", "Gracias por tu oferta.")
            )

    def _send_document(self, chat_id: int, file_path: str) -> None:
        try:
            with open(file_path, "rb") as f:
                requests.post(
                    f"https://api.telegram.org/bot{self.token}/sendDocument",
                    data={"chat_id": chat_id},
                    files={"document": (Path(file_path).name, f)},
                    timeout=30,
                )
        except Exception as e:
            _log(f"ERR al enviar documento: {e}")

    async def _reset_thread(self, thread_id: str) -> None:
        if self._checkpointer_override is not None:
            await self._checkpointer_override.setup()
            await self._checkpointer_override.adelete_thread(thread_id)
        else:
            async with checkpointer_scope() as checkpointer:
                await checkpointer.adelete_thread(thread_id)

    # ── Agente ReAct (LangGraph) ──────────────────────────────────────────────

    async def _run_agent(self, chat_id: int, username: str, text: str) -> str:
        tools = self._build_tools(chat_id)
        config = {"configurable": {"thread_id": str(chat_id)}, "recursion_limit": 20}

        try:
            if self._checkpointer_override is not None:
                agent = create_agent(
                    model=self.model,
                    tools=tools,
                    system_prompt=SYSTEM_PROMPT,
                    checkpointer=self._checkpointer_override,
                )
                result = await agent.ainvoke(
                    {"messages": [HumanMessage(content=text)]}, config=config
                )
            else:
                async with checkpointer_scope() as checkpointer:
                    agent = create_agent(
                        model=self.model,
                        tools=tools,
                        system_prompt=SYSTEM_PROMPT,
                        checkpointer=checkpointer,
                    )
                    result = await agent.ainvoke(
                        {"messages": [HumanMessage(content=text)]}, config=config
                    )
        except Exception as e:
            _log(f"ERR  [{username}] error del agente: {e}")
            return f"⚠️ Error al conectar con la IA: {e}"

        for message in reversed(result["messages"]):
            if isinstance(message, AIMessage) and message.content:
                return message.content
        return "No pude generar una respuesta."

    def _build_tools(self, chat_id: int) -> list:
        """Construye las tools por request — closures que capturan chat_id para
        poder avisar al usuario ('Buscando...') antes de operaciones lentas."""

        @tool("buscar_autos", args_schema=BuscarAutosArgs)
        async def buscar_autos(
            ciudad: str,
            modelo: str = "",
            precio_min: int = 0,
            precio_max: int = 0,
            cantidad: int = 3,
        ) -> str:
            """Busca y analiza autos en Facebook Marketplace de una ciudad peruana. Tarda 1-3 minutos. SOLO puede llamarse UNA VEZ por turno."""
            if not modelo and precio_min == 0 and precio_max == 0:
                precio_min, precio_max = 3000, 15000
            sin_filtro = precio_min == 0 and precio_max == 0
            self.send_message(
                chat_id,
                f"🔍 Buscando{' ' + modelo if modelo else ''} en Facebook Marketplace"
                f"{' (sin filtro de precio)' if sin_filtro else ''}... esto tarda 1-2 minutos ⏳",
            )
            return await self._tool_buscar_autos(
                ciudad=ciudad,
                modelo=modelo,
                precio_min=precio_min,
                precio_max=precio_max,
                cantidad=min(cantidad, 5),
            )

        @tool("ver_pipeline", args_schema=VerPipelineArgs)
        async def ver_pipeline(estado: str = "todos") -> str:
            """Muestra los autos guardados en Airtable, opcionalmente filtrados por estado del pipeline."""
            return self._tool_ver_pipeline(estado)

        @tool("analizar_url", args_schema=AnalizarUrlArgs)
        async def analizar_url(url: str) -> str:
            """Analiza un auto específico a partir de su URL de Facebook Marketplace."""
            self.send_message(chat_id, "🔎 Analizando el auto... un momento ⏳")
            return await self._tool_analizar_url(url)

        @tool("actualizar_estado", args_schema=ActualizarEstadoArgs)
        async def actualizar_estado(titulo_parcial: str, nuevo_estado: str) -> str:
            """Actualiza el estado del pipeline de un auto guardado en Airtable."""
            return self._tool_actualizar_estado(titulo_parcial, nuevo_estado)

        @tool("resumen", args_schema=ResumenArgs)
        async def resumen() -> str:
            """Muestra estadísticas generales: autos por estado, ganancia potencial y real."""
            return self._tool_resumen()

        return [buscar_autos, ver_pipeline, analizar_url, actualizar_estado, resumen]

    # ── Implementación: buscar_autos ──────────────────────────────────────────

    async def _tool_buscar_autos(
        self,
        ciudad: str = "lima",
        modelo: str = "",
        precio_min: int = 0,
        precio_max: int = 0,
        cantidad: int = 3,
    ) -> str:
        from tools.scraper_tool import FacebookScraper

        scraper = FacebookScraper(
            city=ciudad, min_price=precio_min, max_price=precio_max, query=modelo
        )
        autos = await scraper.scrape_cars(cantidad)
        orch = Orchestrator(api_key=self.groq_key)

        aptos: list[tuple[dict, object]] = []
        rechazados = 0
        for auto in autos:
            if is_seen(auto.get("url", "")):
                continue
            try:
                state = await orch.run_acquisition(car_data=auto)
                mark_seen(auto.get("url", ""), auto.get("title", ""))
                if state.car_data.get("apto_venta"):
                    aptos.append((auto, state))
                else:
                    rechazados += 1
            except Exception:
                rechazados += 1

        total = len(autos)
        if total == 0:
            return (
                "No se encontraron autos. Facebook puede estar bloqueando el acceso temporalmente. "
                "Intenta en unos minutos o prueba otra ciudad."
            )
        if not aptos:
            return (
                f"Se analizaron {total} auto(s) en {ciudad.title()} pero ninguno es rentable.\n"
                "Prueba con otro modelo o amplía el rango de precio."
            )

        lines = [
            f"✅ *{len(aptos)} oportunidad(es) encontrada(s)* de {total} analizado(s) en {ciudad.title()}:\n"
        ]
        for auto, state in aptos:
            cd = state.car_data
            pm = cd.get("precio_mercado") or 0
            pv = cd.get("precio_venta") or 0
            gan = cd.get("ganancia_est") or 0
            pct = cd.get("margen_pct") or 0
            lines.append(f"🚗 *{auto.get('title', '?')}*")
            lines.append(
                f"   💵 Publicado: {auto.get('price', '?')}  |  Mercado: ${pm:,.0f}"
            )
            lines.append(
                f"   🎯 Máx. pagar: ${pv:,.0f}  |  💰 Ganancia: ${gan:,.0f} ({pct:.0f}%)"
            )
            if auto.get("url"):
                lines.append(f"   🔗 {auto['url']}")
            if auto.get("whatsapp_number"):
                lines.append(f"   📱 +{auto['whatsapp_number']}")
            lines.append("")
        if rechazados:
            lines.append(f"_({rechazados} auto(s) descartados por no ser rentables)_")
        return "\n".join(lines)

    # ── Implementación: ver_pipeline ──────────────────────────────────────────

    def _tool_ver_pipeline(self, estado: str = "todos") -> str:
        if not self.airtable.is_configured():
            return "⚠️ Airtable no está configurado. Conéctalo en la app web (pestaña Configuración)."

        cars = self.airtable.get_approved_cars(max_records=100)
        if not cars:
            return "📭 No tienes autos guardados aún."

        if estado != "todos":
            cars = [c for c in cars if c.get("Pipeline", "Encontrado") == estado]
            if not cars:
                return f"No tienes autos en estado *{estado}*."

        emojis = {
            "Encontrado": "🔵",
            "Contactando": "🟡",
            "Negociando": "🟠",
            "Comprado": "🟣",
            "Vendido": "🟢",
        }
        groups: dict[str, list] = {}
        for c in cars:
            groups.setdefault(c.get("Pipeline", "Encontrado"), []).append(c)

        lines = [f"📋 *Pipeline* ({len(cars)} auto(s)):\n"]
        for stage in _PIPELINE_STATES:
            grp = groups.get(stage, [])
            if not grp:
                continue
            lines.append(f"{emojis.get(stage, '•')} *{stage}* ({len(grp)})")
            for c in grp:
                title = str(c.get("Título", "?"))[:50]
                pub = c.get("Precio Publicado") or 0
                merc = c.get("Precio Mercado") or 0
                gan_c = max(merc - pub, 0)
                suffix = f" — +${gan_c:,.0f}" if gan_c else ""
                lines.append(f"  • {title}{suffix}")
            lines.append("")
        return "\n".join(lines)

    # ── Implementación: analizar_url ──────────────────────────────────────────

    async def _tool_analizar_url(self, url: str) -> str:
        if not re.search(r"facebook\.com/marketplace/item/\d+", url):
            return "⚠️ La URL no parece ser un listing válido de Facebook Marketplace."

        from tools.scraper_tool import scrape_item_url

        car_data = await scrape_item_url(url)
        if not car_data:
            return "No pude acceder al listing. Puede que Facebook esté bloqueando el acceso."

        orch = Orchestrator(api_key=self.groq_key)
        try:
            state = await orch.run_acquisition(car_data=car_data)
        except Exception as e:
            return f"Error al analizar el listing: {e}"
        mark_seen(url, car_data.get("title", ""))

        cd = state.car_data
        pm = cd.get("precio_mercado") or 0
        pv = cd.get("precio_venta") or 0
        gan = cd.get("ganancia_est") or 0
        pct = cd.get("margen_pct") or 0
        apto = bool(cd.get("apto_venta"))

        icon = "✅" if apto else "❌"
        lines = [
            f"{icon} *{car_data.get('title', '?')}*",
            "",
            f"💵 Publicado: {car_data.get('price', '?')}",
            f"📊 Valor mercado: ${pm:,.0f}",
            f"🎯 Máx. a pagar: ${pv:,.0f}",
            f"💰 Ganancia est.: ${gan:,.0f} ({pct:.0f}%)",
            "",
        ]
        red_flags = cd.get("red_flags", [])
        green_flags = cd.get("green_flags", [])
        if red_flags:
            lines.append("⚠️ *Alertas:*")
            lines.extend(f"  • {f}" for f in red_flags[:4])
            lines.append("")
        if green_flags:
            lines.append("✅ *Puntos a favor:*")
            lines.extend(f"  • {f}" for f in green_flags[:4])
            lines.append("")
        obs = (
            state.inspection_data.get("observaciones")
            or state.inspection_data.get("resultado_inspeccion")
            or ""
        )
        if obs:
            lines.append(f"📋 _{obs[:350]}{'...' if len(obs) > 350 else ''}_")
        if car_data.get("whatsapp_number") and apto:
            lines.append(f"\n📱 WhatsApp vendedor: +{car_data['whatsapp_number']}")
        return "\n".join(lines)

    # ── Implementación: actualizar_estado ─────────────────────────────────────

    def _tool_actualizar_estado(self, titulo_parcial: str, nuevo_estado: str) -> str:
        if not self.airtable.is_configured():
            return "⚠️ Airtable no está configurado."
        if not titulo_parcial:
            return "Necesito el nombre (o parte del nombre) del auto para buscarlo."

        cars = self.airtable.get_approved_cars(max_records=100)
        matches = [
            c
            for c in cars
            if titulo_parcial.lower() in str(c.get("Título", "")).lower()
        ]

        if not matches:
            return (
                f"No encontré ningún auto que coincida con *{titulo_parcial}*.\n"
                "Verifica el nombre o usa más palabras del título."
            )
        if len(matches) > 1:
            titles = "\n".join(f"• {c.get('Título', '?')}" for c in matches[:5])
            return (
                f"Encontré {len(matches)} coincidencias. Sé más específico:\n{titles}"
            )

        car = matches[0]
        result = self.airtable.update_car(
            car.get("_id", ""), {"Pipeline": nuevo_estado}
        )
        if result:
            return f"✅ *{car.get('Título', '?')}* → *{nuevo_estado}*"
        return "❌ No pude actualizar el registro. Revisa la configuración de Airtable."

    # ── Implementación: resumen ────────────────────────────────────────────────

    def _tool_resumen(self) -> str:
        if not self.airtable.is_configured():
            return "⚠️ Airtable no está configurado."

        cars = self.airtable.get_approved_cars(max_records=500)
        if not cars:
            return "📭 Aún no tienes datos. Empieza buscando autos desde la app o desde aquí."

        total = len(cars)
        pipeline: dict[str, int] = {}
        gan_pot = 0.0
        gan_real = 0.0

        for c in cars:
            stage = c.get("Pipeline", "Encontrado")
            pipeline[stage] = pipeline.get(stage, 0) + 1
            pub = c.get("Precio Publicado") or 0
            merc = c.get("Precio Mercado") or 0
            gan_pot += max(merc - pub, 0)
            gan_real += c.get("Ganancia Real") or 0

        emojis = {
            "Encontrado": "🔵",
            "Contactando": "🟡",
            "Negociando": "🟠",
            "Comprado": "🟣",
            "Vendido": "🟢",
        }
        lines = [f"📊 *Resumen Anymotor* ({total} autos)\n"]
        for stage in _PIPELINE_STATES:
            count = pipeline.get(stage, 0)
            if count:
                lines.append(f"{emojis.get(stage, '•')} {stage}: {count}")

        lines.append(f"\n💰 Ganancia potencial: *${gan_pot:,.0f}*")
        if gan_real > 0:
            lines.append(f"✅ Ganancia real: *${gan_real:,.0f}*")
            vendidos = pipeline.get("Vendido", 0)
            if vendidos:
                lines.append(
                    f"📈 Promedio por auto vendido: *${gan_real / vendidos:,.0f}*"
                )
        return "\n".join(lines)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _split_text(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        chunks.append(text[:limit])
        text = text[limit:]
    return chunks


_OFFER_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(k|mil)?", re.IGNORECASE)


def _extract_offer(text: str) -> float | None:
    """Heurística simple para demo: toma el último número mencionado en el
    mensaje como la oferta del cliente (ej. "te ofrezco 8000" -> 8000.0).

    No es NLU robusto — con mensajes ambiguos ("tiene 45000 km, ofrezco 8000")
    puede confundirse. Suficiente para una demo con inputs controlados; para
    producción real convendría pedirle al LLM que extraiga el monto."""
    matches = _OFFER_RE.findall(text)
    if not matches:
        return None
    num_str, suffix = matches[-1]
    try:
        value = float(num_str.replace(",", ""))
    except ValueError:
        return None
    if suffix:
        value *= 1000
    return value if value >= 100 else None


_ACCEPTANCE_RE = re.compile(
    r"\b(acepto|aceptar|aceptamos|trato hecho|de acuerdo|me parece bien)\b",
    re.IGNORECASE,
)


def _is_acceptance(text: str) -> bool:
    """Detecta que el cliente acepta una oferta en lenguaje natural, sin
    repetir el número (ej. "me parece bien, acepto")."""
    return bool(_ACCEPTANCE_RE.search(text))


# ── Recolección secuencial de datos del comprador antes de cerrar ──────────

_CLOSING_STEP_ORDER = ["nombre", "dni", "correo", "fecha"]
_CLOSING_PROMPTS = {
    "nombre": "¿Cuál es tu nombre completo?",
    "dni": "Gracias. Ahora tu DNI (8 dígitos), por favor.",
    "correo": "Perfecto. ¿Cuál es tu correo electrónico?",
    "fecha": "Último dato: ¿qué fecha te gustaría para la cita?",
}
_DNI_RE = re.compile(r"^\d{8}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _next_closing_step(current: str) -> str | None:
    idx = _CLOSING_STEP_ORDER.index(current)
    return _CLOSING_STEP_ORDER[idx + 1] if idx + 1 < len(_CLOSING_STEP_ORDER) else None


def _validate_closing_field(step: str, text: str) -> tuple[bool, str]:
    """Valida la respuesta a un paso de la recolección de datos del cierre.

    Retorna (True, valor_limpio) si es válida, o (False, mensaje_de_error)
    si hay que volver a pedirla."""
    value = text.strip()
    if step == "nombre":
        if len(value) < 3:
            return False, "Ese nombre parece muy corto — ¿me confirmás tu nombre completo?"
        return True, value
    if step == "dni":
        if not _DNI_RE.match(value):
            return False, "El DNI debe tener 8 dígitos numéricos. ¿Podés confirmarlo?"
        return True, value
    if step == "correo":
        if not _EMAIL_RE.match(value):
            return False, "Ese correo no parece válido. ¿Podés escribirlo de nuevo?"
        return True, value
    # step == "fecha": se acepta cualquier texto no vacío.
    if not value:
        return False, "¿Qué fecha te gustaría para la cita?"
    return True, value

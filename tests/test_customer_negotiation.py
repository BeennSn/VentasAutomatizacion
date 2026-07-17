"""Tests for the customer-facing Telegram negotiation flow (non-owner chats)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agents.telegram_bot_agent import TelegramBotAgent, _extract_offer, _is_acceptance
from shared.graph_state import CarSaleState
from shared.listings_store import get_listing, save_listing


# ── _extract_offer ──────────────────────────────────────────────────────────


def test_extract_offer_simple():
    assert _extract_offer("te ofrezco 8000") == 8000.0


def test_extract_offer_with_k_suffix():
    assert _extract_offer("puedo pagar 7.5k") == 7500.0


def test_extract_offer_no_number():
    assert _extract_offer("me interesa mucho el auto") is None


def test_extract_offer_ignores_small_numbers():
    assert _extract_offer("hola, como va") is None


# ── _is_acceptance ──────────────────────────────────────────────────────────


def test_is_acceptance_detects_phrases():
    assert _is_acceptance("Me parece bien ese precio, acepto")
    assert _is_acceptance("de acuerdo, cerremos")
    assert _is_acceptance("Trato hecho")


def test_is_acceptance_false_for_unrelated_text():
    assert not _is_acceptance("hola, como va")
    assert not _is_acceptance("necesito llevar el auto a revisar")


# ── shared/listings_store ───────────────────────────────────────────────────


def test_listings_store_roundtrip():
    save_listing("test-car-123", {"marca": "Toyota", "modelo": "Yaris"})
    assert get_listing("test-car-123") == {"marca": "Toyota", "modelo": "Yaris"}


def test_listings_store_missing_returns_none():
    assert get_listing("no-existe-nunca-123456") is None


# ── TelegramBotAgent — flujo de cliente ─────────────────────────────────────


@pytest.fixture
def bot():
    return TelegramBotAgent(token="fake", groq_key="fake", allowed_users=["1"])


def test_handle_customer_start_with_known_car(bot):
    save_listing("demo-car-1", {"marca": "Toyota", "modelo": "Corolla", "año": 2019})
    with patch.object(bot, "send_message") as mock_send:
        bot._handle_customer(chat_id=99, username="cliente", text="/start neg_demo-car-1")

    assert 99 in bot._customer_states
    assert bot._customer_states[99].car_data["modelo"] == "Corolla"
    mock_send.assert_called_once()
    assert "Corolla" in mock_send.call_args[0][1]


def test_handle_customer_start_with_unknown_car(bot):
    with patch.object(bot, "send_message") as mock_send:
        bot._handle_customer(chat_id=100, username="cliente", text="/start neg_no-existe")

    assert 100 not in bot._customer_states
    mock_send.assert_called_once()
    assert "no encontré" in mock_send.call_args[0][1].lower()


def test_handle_customer_without_context(bot):
    with patch.object(bot, "send_message") as mock_send:
        bot._handle_customer(chat_id=101, username="cliente", text="hola, cuanto cuesta?")

    mock_send.assert_called_once()
    assert "consultar y negociar" in mock_send.call_args[0][1].lower()


@pytest.mark.asyncio
async def test_run_customer_turn_question_only(bot):
    state = CarSaleState(
        car_data={"marca": "Toyota", "modelo": "Corolla", "año": 2019, "precio_mercado": 14000}
    )
    with patch("agents.telegram_bot_agent.CRMChatbotAgent") as MockCRM, patch.object(
        bot, "send_message"
    ) as mock_send:
        MockCRM.return_value.handle_message = AsyncMock(
            return_value={"respuesta_cliente": "Claro, sigue disponible.", "lead_calificado": False}
        )
        await bot._run_customer_turn(
            chat_id=1, username="cliente", text="¿sigue disponible?", state=state
        )

    mock_send.assert_called_once_with(1, "Claro, sigue disponible.")


@pytest.mark.asyncio
async def test_run_customer_turn_offer_accepted(bot):
    state = CarSaleState(
        car_data={"marca": "Toyota", "modelo": "Corolla", "año": 2019, "precio_mercado": 14000}
    )
    with patch("agents.telegram_bot_agent.CRMChatbotAgent") as MockCRM, patch(
        "agents.telegram_bot_agent.SalesClosingAgent"
    ) as MockClosing, patch.object(bot, "send_message") as mock_send, patch.object(
        bot, "_send_document"
    ) as mock_doc:
        MockCRM.return_value.handle_message = AsyncMock(
            return_value={"respuesta_cliente": "ok", "lead_calificado": True}
        )
        MockClosing.return_value.negotiate = AsyncMock(
            return_value={
                "venta_completada": True,
                "precio_final": 13000,
                "mensaje_cliente": "Trato hecho.",
            }
        )
        await bot._run_customer_turn(
            chat_id=2, username="cliente", text="te ofrezco 13000", state=state
        )

    mock_send.assert_called_once()
    assert "13,000" in mock_send.call_args[0][1]
    mock_doc.assert_not_called()


@pytest.mark.asyncio
async def test_run_customer_turn_offer_rejected(bot):
    state = CarSaleState(
        car_data={"marca": "Toyota", "modelo": "Corolla", "año": 2019, "precio_mercado": 14000}
    )
    with patch("agents.telegram_bot_agent.CRMChatbotAgent") as MockCRM, patch(
        "agents.telegram_bot_agent.SalesClosingAgent"
    ) as MockClosing, patch.object(bot, "send_message") as mock_send:
        MockCRM.return_value.handle_message = AsyncMock(
            return_value={"respuesta_cliente": "ok", "lead_calificado": True}
        )
        MockClosing.return_value.negotiate = AsyncMock(
            return_value={
                "venta_completada": False,
                "contraoferta": 12000,
                "mensaje_cliente": "Puedo bajar hasta 12000.",
            }
        )
        await bot._run_customer_turn(
            chat_id=3, username="cliente", text="te ofrezco 8000", state=state
        )

    mock_send.assert_called_once_with(3, "Puedo bajar hasta 12000.")


@pytest.mark.asyncio
async def test_run_customer_turn_accepts_counteroffer_via_natural_language(bot):
    """Regresión del bug reportado en vivo: el cliente rechaza con un número,
    recibe una contraoferta, y la acepta sin repetir el monto ("acepto")."""
    state = CarSaleState(
        car_data={"marca": "Toyota", "modelo": "Corolla", "año": 2019, "precio_mercado": 14000}
    )
    with patch("agents.telegram_bot_agent.CRMChatbotAgent") as MockCRM, patch(
        "agents.telegram_bot_agent.SalesClosingAgent"
    ) as MockClosing, patch.object(bot, "send_message"), patch.object(
        bot, "_send_document"
    ) as mock_doc:
        MockCRM.return_value.handle_message = AsyncMock(
            return_value={"respuesta_cliente": "ok", "lead_calificado": True}
        )
        MockClosing.return_value.negotiate = AsyncMock(
            return_value={
                "venta_completada": False,
                "contraoferta": 10625,
                "mensaje_cliente": "Puedo bajar hasta 10625.",
            }
        )
        await bot._run_customer_turn(
            chat_id=4, username="cliente", text="ofrezco 8900", state=state
        )
        assert bot._last_counteroffer[4] == 10625

        # Segundo turno: acepta en lenguaje natural, sin repetir el número.
        MockClosing.return_value.negotiate = AsyncMock(
            return_value={
                "venta_completada": True,
                "precio_final": 10625,
                "mensaje_cliente": "Trato hecho.",
            }
        )
        await bot._run_customer_turn(
            chat_id=4,
            username="cliente",
            text="Me parece bien ese precio, acepto",
            state=state,
        )

    MockClosing.return_value.negotiate.assert_called_with(offer=10625, state=state)
    assert 4 not in bot._last_counteroffer
    mock_doc.assert_not_called()


@pytest.mark.asyncio
async def test_run_customer_turn_collects_buyer_data_then_closes(bot):
    """Flujo completo: oferta aceptada -> el bot pide nombre, DNI, correo y
    fecha uno por uno -> recién con todo completo cierra la venta de verdad."""
    state = CarSaleState(
        car_data={"marca": "Toyota", "modelo": "Corolla", "año": 2019, "precio_mercado": 14000}
    )

    with patch("agents.telegram_bot_agent.CRMChatbotAgent") as MockCRM, patch(
        "agents.telegram_bot_agent.SalesClosingAgent"
    ) as MockClosing, patch.object(bot, "send_message") as mock_send:
        MockCRM.return_value.handle_message = AsyncMock(
            return_value={"respuesta_cliente": "ok", "lead_calificado": True}
        )
        MockClosing.return_value.negotiate = AsyncMock(
            return_value={
                "oferta_aceptable": True,
                "requiere_datos_cierre": True,
                "venta_completada": False,
                "precio_final": 12500,
                "mensaje_cliente": "¡Trato hecho!",
            }
        )
        await bot._run_customer_turn(
            chat_id=5, username="cliente", text="te ofrezco 12500", state=state
        )

    assert bot._pending_close[5] == {"offer": 12500, "step": "nombre", "datos": {}}
    mock_send.assert_called_once_with(5, "¡Trato hecho!\n\n¿Cuál es tu nombre completo?")

    # Nombre -> avanza a DNI.
    with patch.object(bot, "send_message") as mock_send:
        await bot._run_customer_turn(chat_id=5, username="cliente", text="Juan Perez", state=state)
    assert bot._pending_close[5]["step"] == "dni"
    assert bot._pending_close[5]["datos"]["nombre"] == "Juan Perez"
    mock_send.assert_called_once_with(5, "Gracias. Ahora tu DNI (8 dígitos), por favor.")

    # DNI inválido -> vuelve a pedirlo, no avanza de paso.
    with patch.object(bot, "send_message") as mock_send:
        await bot._run_customer_turn(chat_id=5, username="cliente", text="123", state=state)
    assert bot._pending_close[5]["step"] == "dni"
    mock_send.assert_called_once()

    # DNI válido -> avanza a correo.
    with patch.object(bot, "send_message") as mock_send:
        await bot._run_customer_turn(chat_id=5, username="cliente", text="87654321", state=state)
    assert bot._pending_close[5]["step"] == "correo"
    assert bot._pending_close[5]["datos"]["dni"] == "87654321"

    # Correo -> avanza a fecha.
    with patch.object(bot, "send_message") as mock_send:
        await bot._run_customer_turn(
            chat_id=5, username="cliente", text="juan@correo.com", state=state
        )
    assert bot._pending_close[5]["step"] == "fecha"
    mock_send.assert_called_once_with(5, "Último dato: ¿qué fecha te gustaría para la cita?")

    # Fecha -> con todo completo, cierra de verdad.
    with patch("agents.telegram_bot_agent.SalesClosingAgent") as MockClosing2, patch.object(
        bot, "send_message"
    ) as mock_send2, patch.object(bot, "_send_document"):
        MockClosing2.return_value.negotiate = AsyncMock(
            return_value={
                "venta_completada": True,
                "precio_final": 12500,
                "mensaje_cliente": "Trato cerrado.",
            }
        )
        await bot._run_customer_turn(
            chat_id=5, username="cliente", text="jueves 4pm", state=state
        )

    MockClosing2.return_value.negotiate.assert_called_once_with(
        offer=12500,
        state=state,
        fecha_cita="jueves 4pm",
        datos_comprador={"nombre": "Juan Perez", "dni": "87654321", "correo": "juan@correo.com"},
    )
    assert 5 not in bot._pending_close
    mock_send2.assert_called_once()
    assert "Trato cerrado" in mock_send2.call_args[0][1]
    assert "Trato cerrado" in mock_send2.call_args[0][1]

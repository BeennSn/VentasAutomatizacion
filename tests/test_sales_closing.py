from unittest.mock import AsyncMock, patch

import pytest

from agents.sales_closing_agent import (
    ResumenContrato,
    SalesClosingAgent,
    SalesClosingResult,
)
from shared.graph_state import CarSaleState


@pytest.mark.asyncio
async def test_sale_completed():
    agent = SalesClosingAgent(api_key="test")
    agent.llm = AsyncMock(
        ainvoke=AsyncMock(
            return_value=SalesClosingResult(
                resumen_contrato=ResumenContrato(
                    vendedor="Vendedor Demo",
                    comprador="Cliente Demo",
                    vehiculo="Toyota Corolla 2019",
                    precio=12000,
                    forma_pago="transferencia",
                    fecha="2026-05-20",
                    clausulas=["Se vende en el estado actual."],
                ),
                mensaje_cliente="Trato hecho.",
            )
        )
    )

    state = CarSaleState(
        car_data={
            "marca": "Toyota",
            "modelo": "Corolla",
            "año": 2019,
            "km": 45000,
            "precio_mercado": 14000,
        },
        lead_data={"nombre_cliente": "Cliente Demo"},
    )
    out = await agent.negotiate(
        offer=12000,
        state=state,
        fecha_cita="jueves 4pm",
        datos_comprador={"nombre": "Cliente Demo", "dni": "12345678", "correo": "cliente@test.com"},
    )
    assert out["venta_completada"] is True
    assert state.status == "sold"
    assert state.sale_data["fecha_cita"] == "jueves 4pm"
    assert state.sale_data["comprador_dni"] == "12345678"


@pytest.mark.asyncio
async def test_negotiate_requires_datos_cierre_before_closing():
    """La primera vez que se acepta una oferta, no debe cerrar todavía: hay
    que pedirle nombre/DNI/correo/fecha al cliente antes de generar el
    contrato."""
    agent = SalesClosingAgent(api_key="test")
    agent.llm = AsyncMock(ainvoke=AsyncMock(side_effect=AssertionError("no debería llamar al LLM")))

    state = CarSaleState(
        car_data={"marca": "Toyota", "modelo": "Corolla", "año": 2019, "precio_mercado": 14000},
    )
    out = await agent.negotiate(offer=12000, state=state)

    assert out["oferta_aceptable"] is True
    assert out["requiere_datos_cierre"] is True
    assert out["venta_completada"] is False
    assert state.status != "sold"


@pytest.mark.asyncio
async def test_negotiate_still_pending_with_only_fecha_and_no_datos_comprador():
    """No basta con la fecha sola: si faltan nombre/DNI/correo, sigue pendiente."""
    agent = SalesClosingAgent(api_key="test")
    agent.llm = AsyncMock(ainvoke=AsyncMock(side_effect=AssertionError("no debería llamar al LLM")))

    state = CarSaleState(
        car_data={"marca": "Toyota", "modelo": "Corolla", "año": 2019, "precio_mercado": 14000},
    )
    out = await agent.negotiate(offer=12000, state=state, fecha_cita="jueves 4pm")

    assert out["requiere_datos_cierre"] is True
    assert out["venta_completada"] is False


@pytest.mark.asyncio
async def test_negotiate_closes_after_all_data_on_second_call():
    agent = SalesClosingAgent(api_key="test")
    state = CarSaleState(
        car_data={"marca": "Toyota", "modelo": "Corolla", "año": 2019, "precio_mercado": 14000},
    )

    agent.llm = AsyncMock(ainvoke=AsyncMock(side_effect=AssertionError("no deberia llamar al LLM")))
    first = await agent.negotiate(offer=12000, state=state)
    assert first["requiere_datos_cierre"] is True

    agent.llm = AsyncMock(
        ainvoke=AsyncMock(
            return_value=SalesClosingResult(
                resumen_contrato=ResumenContrato(
                    vendedor="Anymotor", comprador="Cliente", vehiculo="Toyota Corolla 2019",
                    precio=12000, forma_pago="efectivo", clausulas=[],
                ),
                mensaje_cliente="Trato hecho.",
            )
        )
    )
    second = await agent.negotiate(
        offer=12000,
        state=state,
        fecha_cita="viernes 10am",
        datos_comprador={"nombre": "Juan Perez", "dni": "87654321", "correo": "juan@test.com"},
    )
    assert second["venta_completada"] is True
    assert state.status == "sold"
    assert state.sale_data["fecha_cita"] == "viernes 10am"
    assert state.sale_data["comprador_nombre"] == "Juan Perez"
    assert state.sale_data["comprador_correo"] == "juan@test.com"


@pytest.mark.asyncio
async def test_negotiate_sends_whatsapp_alert_on_close():
    agent = SalesClosingAgent(api_key="test")
    agent.llm = AsyncMock(
        ainvoke=AsyncMock(
            return_value=SalesClosingResult(
                resumen_contrato=ResumenContrato(
                    vendedor="Anymotor", comprador="Cliente", vehiculo="Toyota Corolla 2019",
                    precio=12000, forma_pago="efectivo", clausulas=[],
                ),
                mensaje_cliente="Trato hecho.",
            )
        )
    )
    state = CarSaleState(
        car_data={"marca": "Toyota", "modelo": "Corolla", "año": 2019, "precio_mercado": 14000},
    )

    datos = {"nombre": "Cliente Demo", "dni": "12345678", "correo": "cliente@test.com"}
    with patch("agents.sales_closing_agent.WhatsAppTool") as MockWhatsApp:
        MockWhatsApp.return_value.is_configured.return_value = True
        await agent.negotiate(
            offer=12000, state=state, fecha_cita="jueves 4pm", datos_comprador=datos
        )

    MockWhatsApp.return_value.send_sale_closed_alert.assert_called_once()


@pytest.mark.asyncio
async def test_negotiate_falls_back_to_telegram_when_whatsapp_not_configured():
    agent = SalesClosingAgent(api_key="test")
    agent.llm = AsyncMock(
        ainvoke=AsyncMock(
            return_value=SalesClosingResult(
                resumen_contrato=ResumenContrato(
                    vendedor="Anymotor", comprador="Cliente", vehiculo="Toyota Corolla 2019",
                    precio=12000, forma_pago="efectivo", clausulas=[],
                ),
                mensaje_cliente="Trato hecho.",
            )
        )
    )
    state = CarSaleState(
        car_data={"marca": "Toyota", "modelo": "Corolla", "año": 2019, "precio_mercado": 14000},
    )

    datos = {"nombre": "Cliente Demo", "dni": "12345678", "correo": "cliente@test.com"}
    with patch("agents.sales_closing_agent.WhatsAppTool") as MockWhatsApp, patch(
        "agents.sales_closing_agent.TelegramNotifier"
    ) as MockTelegram:
        MockWhatsApp.return_value.is_configured.return_value = False
        await agent.negotiate(
            offer=12000, state=state, fecha_cita="jueves 4pm", datos_comprador=datos
        )

    MockWhatsApp.return_value.send_sale_closed_alert.assert_not_called()
    MockTelegram.return_value.send_sale_closed_alert.assert_called_once()


@pytest.mark.asyncio
async def test_contract_pdf_survives_unicode_clauses():
    """Regresión: comillas curvas / guiones largos del LLM no deben romper el PDF."""
    agent = SalesClosingAgent(api_key="test")
    agent.llm = AsyncMock(
        ainvoke=AsyncMock(
            return_value=SalesClosingResult(
                resumen_contrato=ResumenContrato(
                    vendedor="Vendedor Demo",
                    comprador="Cliente Demo",
                    vehiculo="Toyota Corolla 2019",
                    precio=12000,
                    forma_pago="transferencia",
                    fecha="2026-05-20",
                    clausulas=[
                        "El auto se entrega “como está” — sin garantía adicional.",
                        "Plazo de entrega: 48 horas… sujeto a coordinación.",
                    ],
                ),
                mensaje_cliente="Trato hecho.",
            )
        )
    )

    state = CarSaleState(
        car_data={
            "marca": "Toyota",
            "modelo": "Corolla",
            "año": 2019,
            "km": 45000,
            "precio_mercado": 14000,
        },
        lead_data={"nombre_cliente": "Cliente Demo"},
    )
    out = await agent.negotiate(
        offer=12000,
        state=state,
        fecha_cita="sabado 11am",
        datos_comprador={"nombre": "Cliente Demo", "dni": "12345678", "correo": "cliente@test.com"},
    )
    assert out["venta_completada"] is True
    assert state.sale_data["contrato_pdf"]


@pytest.mark.asyncio
async def test_counteroffer_never_increases_between_attempts():
    """Regresión de bug real: el cliente subió su oferta de 8800 a 10500 y la
    contraoferta subió de 10625 a 10800 — ilógico. El LLM no debería poder
    subir la contraoferta respecto a la anterior, y el código lo refuerza
    aunque el LLM (mockeado acá) intente devolver una más alta."""
    agent = SalesClosingAgent(api_key="test")
    state = CarSaleState(
        car_data={
            "marca": "Hyundai",
            "modelo": "Accent",
            "año": 2018,
            "precio_mercado": 12500,
        },
    )

    agent.llm = AsyncMock(
        ainvoke=AsyncMock(
            return_value=SalesClosingResult(
                contraoferta=None,  # sin sugerencia -> cae al fallback max(min_aceptable, offer)
                mensaje_cliente="Puedo bajar hasta ahí.",
            )
        )
    )
    first = await agent.negotiate(offer=8800, state=state)
    assert first["oferta_aceptable"] is False
    assert first["contraoferta"] == 10625.0  # min_aceptable = 12500 * 0.85

    # El LLM esta vez "quiere" subir el pedido a 10800 pese a que la oferta
    # del cliente subió (10500) -> el código debe recortarlo a la anterior.
    agent.llm = AsyncMock(
        ainvoke=AsyncMock(
            return_value=SalesClosingResult(
                contraoferta=10800,
                mensaje_cliente="Lo mínimo que puedo aceptar es esto.",
            )
        )
    )
    second = await agent.negotiate(offer=10500, state=state)
    assert second["oferta_aceptable"] is False
    assert second["contraoferta"] <= first["contraoferta"]
    assert second["contraoferta"] == 10625.0

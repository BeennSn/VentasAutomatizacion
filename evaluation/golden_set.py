"""Golden set — evaluation cases with expected outputs per §5.1.

Each case has:
  - id: unique identifier (C-XX)
  - input: car_data dict as it would come from the scraper
  - expected: dict with expected fields from the acquisition agent
  - notes: which requirement this validates
"""

from __future__ import annotations

GOLDEN_SET: list[dict] = [
    {
        "id": "C-01",
        "input": {
            "title": "Toyota Yaris 2016 Full Equipo",
            "price": "$8,500",
            "año": 2016,
            "city": "lima",
            "condition": "Usado - Buen estado",
            "raw_data": "Único dueño, full mantenimiento en concesionario, 65,000 km, AC, airbags, ABS. Color blanco.",
        },
        "expected": {
            "apto_venta": True,
            "precio_mercado_min": 9000,
            "precio_mercado_max": 16000,
        },
        "notes": "RF-01: Auto estrella para flipping, bajo km, único dueño, buen precio → debe ser apto",
    },
    {
        "id": "C-02",
        "input": {
            "title": "Ford F-150 2010 GNV",
            "price": "$12,000",
            "año": 2010,
            "city": "lima",
            "condition": "Usado - Con detalles",
            "raw_data": "Motor reparado, GNV de balón, 210,000 km. Papeles en trámite. 4 dueños.",
        },
        "expected": {
            "apto_venta": False,
        },
        "notes": "RF-02: Múltiples red flags (GNV, motor reparado, +200k km, papeles) → debe rechazar",
    },
    {
        "id": "C-03",
        "input": {
            "title": "Hyundai Accent 2018",
            "price": "S/38,000",
            "año": 2018,
            "city": "lima",
            "condition": "Usado - Como nuevo",
            "raw_data": "Automático, 45,000 km, full equipo. Único dueño. Color gris plata. SOAT vigente.",
        },
        "expected": {
            "apto_venta": True,
            "moneda_detectada": "PEN",
            "precio_mercado_min": 9000,
            "precio_mercado_max": 18000,
        },
        "notes": "RF-03: Precio en soles → debe detectar moneda PEN y convertir correctamente",
    },
    {
        "id": "C-04",
        "input": {
            "title": "Toyota Corolla 2019 Versión Limited",
            "price": "$14,500",
            "año": 2019,
            "city": "lima",
            "condition": "Usado - Buen estado",
            "raw_data": "78,000 km, transmisión automática, gasolina. Mantenimiento con facturas en Toyota. Color negro.",
        },
        "expected": {
            "apto_venta": True,
            "precio_mercado_min": 14000,
            "precio_mercado_max": 24000,
        },
        "notes": "RF-04: Corolla Limited con buen margen → apto con ganancia significativa",
    },
    {
        "id": "C-05",
        "input": {
            "title": "BMW 320i 2015",
            "price": "$13,000",
            "año": 2015,
            "city": "lima",
            "condition": "Usado - Buen estado",
            "raw_data": "120,000 km, automático, gasolina. Mantenimiento costoso. Repuestos importados.",
        },
        "expected": {
            "apto_venta": False,
        },
        "notes": "RF-05: Auto europeo → debe rechazar por costo de mantenimiento alto en Lima",
    },
    {
        "id": "C-06",
        "input": {
            "title": "Kia Rio 2017",
            "price": "$7,200",
            "año": 2017,
            "city": "trujillo",
            "condition": "Usado - Buen estado",
            "raw_data": "85,000 km, manual, gasolina. Segundo dueño. Color blanco. AC, radio bluetooth.",
        },
        "expected": {
            "apto_venta": True,
            "precio_mercado_min": 8000,
            "precio_mercado_max": 15000,
        },
        "notes": "RF-06: Kia Rio buen precio con margen → apto para flipping",
    },
    {
        "id": "C-07",
        "input": {
            "title": "Chevrolet Spark 2014",
            "price": "$6,800",
            "año": 2014,
            "city": "lima",
            "condition": "Usado - Con detalles",
            "raw_data": "145,000 km. Pintura desgastada, golpe leve en guardafango. GLP instalado. 3 dueños.",
        },
        "expected": {
            "apto_venta": False,
        },
        "notes": "RF-07: Precio alto para un Spark con GLP, km alto y golpes → sin margen",
    },
    {
        "id": "C-08",
        "input": {
            "title": "Toyota Hilux 2018 4x4",
            "price": "$24,000",
            "año": 2018,
            "city": "arequipa",
            "condition": "Usado - Buen estado",
            "raw_data": "95,000 km, diesel, manual. Único dueño. Uso particular. Documentos al día.",
        },
        "expected": {
            "apto_venta": True,
            "precio_mercado_min": 24000,
            "precio_mercado_max": 38000,
        },
        "notes": "RF-08: Hilux con buen precio vs mercado → oportunidad de flipping",
    },
    {
        "id": "C-09",
        "input": {
            "title": "Nissan Sentra 2015",
            "price": "$16,000",
            "año": 2015,
            "city": "lima",
            "condition": "Usado - Buen estado",
            "raw_data": "90,000 km, automático. Full equipo. Color azul oscuro.",
        },
        "expected": {
            "apto_venta": False,
        },
        "notes": "RF-09: Precio publicado >= valor de mercado → sin margen, debe rechazar",
    },
    {
        "id": "C-10",
        "input": {
            "title": "Suzuki Swift 2017",
            "price": "$7,000",
            "año": 2017,
            "city": "lima",
            "condition": "Usado - Como nuevo",
            "raw_data": "55,000 km, manual, gasolina. Único dueño, mantenimiento en Suzuki. Color rojo. SOAT y revisión vigente.",
        },
        "expected": {
            "apto_venta": True,
            "precio_mercado_min": 8000,
            "precio_mercado_max": 15000,
        },
        "notes": "RF-10: Swift bajo km, buen estado, precio atractivo → apto",
    },
]

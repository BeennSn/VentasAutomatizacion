"""Tests for FacebookScraper._parse_card_lines — extracción de título/precio
de una tarjeta de Marketplace sin depender del orden de las líneas."""

from __future__ import annotations

from tools.scraper_tool import _parse_card_lines


def test_location_first_does_not_become_title():
    """Regresión del bug real: Facebook mostró la ubicación antes del precio
    y el título, y el scraper se quedaba con 'Pueblo Libre, LM' como título."""
    lines = ["Pueblo Libre, LM", "S/ 12,000", "Toyota Corolla 2015"]
    title, price = _parse_card_lines(lines)
    assert title == "Toyota Corolla 2015"
    assert price == "S/ 12,000"


def test_location_first_with_dollar_price():
    lines = ["Surquillo, LM", "$ 8,500", "Hyundai Accent 2018 Full Equipo"]
    title, price = _parse_card_lines(lines)
    assert title == "Hyundai Accent 2018 Full Equipo"
    assert price == "$ 8,500"


def test_classic_order_price_then_title_then_location():
    lines = ["S/ 25,000", "Toyota Yaris 2018", "Lima, LM"]
    title, price = _parse_card_lines(lines)
    assert title == "Toyota Yaris 2018"
    assert price == "S/ 25,000"


def test_title_with_year_is_not_mistaken_for_price():
    """Un título con un año (4 dígitos) no debe confundirse con el precio
    ahora que el patrón de precio exige un símbolo de moneda al inicio."""
    lines = ["Toyota Corolla 2015 Full", "S/ 12,000", "Miraflores, LM"]
    title, price = _parse_card_lines(lines)
    assert title == "Toyota Corolla 2015 Full"
    assert price == "S/ 12,000"


def test_no_price_symbol_falls_back_to_loose_match():
    lines = ["Pueblo Libre, LM", "12000 negociable", "Kia Rio 2017"]
    title, price = _parse_card_lines(lines)
    assert title == "Kia Rio 2017"
    assert price == "12000 negociable"

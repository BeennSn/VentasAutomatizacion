from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from fpdf import FPDF
from fpdf.enums import XPos, YPos

# La fuente core Helvetica de fpdf2 solo soporta Latin-1. Texto generado por el
# LLM puede traer guiones largos, comillas curvas, etc. que rompen el render
# ("Not enough horizontal space to render a single character") si no se sanean.
_CHAR_REPLACEMENTS = {
    "—": "-",
    "–": "-",
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "…": "...",
    "•": "-",
}

_NAVY = (30, 41, 59)
_GOLD = (180, 138, 40)
_LIGHT_GRAY = (245, 246, 248)
_MID_GRAY = (110, 116, 124)
_BORDER_GRAY = (210, 213, 218)


def _safe_text(value: Any) -> str:
    text = str(value if value is not None else "")
    for bad, good in _CHAR_REPLACEMENTS.items():
        text = text.replace(bad, good)
    return text.encode("latin-1", "replace").decode("latin-1")


def _format_precio(value: Any) -> str:
    try:
        return f"${float(value):,.0f}"
    except (TypeError, ValueError):
        return _safe_text(value)


def generate_contract_pdf(output_path: str | Path, contract: dict[str, Any]) -> str:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    page_w = pdf.w - pdf.l_margin - pdf.r_margin

    # ── Header ───────────────────────────────────────────────────────────────
    pdf.set_fill_color(*_NAVY)
    pdf.rect(0, 0, pdf.w, 32, style="F")
    pdf.set_xy(pdf.l_margin, 8)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(page_w, 10, "ANYMOTOR", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(
        page_w, 7, "Resumen de Contrato de Compraventa Vehicular",
        new_x=XPos.LMARGIN, new_y=YPos.NEXT,
    )
    pdf.set_text_color(0, 0, 0)
    pdf.set_y(40)

    # ── Aviso ────────────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "I", 8.5)
    pdf.set_text_color(*_MID_GRAY)
    pdf.multi_cell(
        page_w,
        4.5,
        _safe_text(
            "Documento interno generado automaticamente como resumen del acuerdo "
            "alcanzado. No reemplaza el contrato de compraventa formal ni el "
            "traspaso notarial/SUNARP requerido para formalizar la transferencia."
        ),
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)

    # ── Datos del acuerdo ────────────────────────────────────────────────────
    fecha = contract.get("fecha") or datetime.now().date().isoformat()
    fields = [
        ("Fecha", _safe_text(fecha)),
        ("Vendedor", _safe_text(contract.get("vendedor", "-"))),
        ("Comprador", _safe_text(contract.get("comprador", "-"))),
        ("Vehiculo", _safe_text(contract.get("vehiculo", "-"))),
        ("Forma de pago", _safe_text(contract.get("forma_pago", "-"))),
    ]
    if contract.get("dni_comprador"):
        fields.append(("DNI comprador", _safe_text(contract["dni_comprador"])))
    if contract.get("correo_comprador"):
        fields.append(("Correo comprador", _safe_text(contract["correo_comprador"])))
    if contract.get("fecha_cita"):
        fields.append(("Fecha de cita", _safe_text(contract["fecha_cita"])))
    label_w = 42
    value_w = page_w - label_w
    pdf.set_font("Helvetica", "", 10.5)
    for i, (label, value) in enumerate(fields):
        pdf.set_fill_color(*(_LIGHT_GRAY if i % 2 == 0 else (255, 255, 255)))
        pdf.set_font("Helvetica", "B", 10.5)
        pdf.cell(label_w, 9, label, border=0, fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.set_font("Helvetica", "", 10.5)
        pdf.cell(value_w, 9, value, border=0, fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # ── Precio destacado ─────────────────────────────────────────────────────
    pdf.ln(3)
    pdf.set_fill_color(*_NAVY)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(page_w, 12, "  PRECIO ACORDADO", border=0, fill=True, new_x=XPos.LMARGIN, new_y=YPos.TOP)
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_xy(pdf.l_margin, pdf.get_y())
    pdf.cell(
        page_w,
        12,
        _format_precio(contract.get("precio", 0)) + "  ",
        border=0,
        fill=True,
        align="R",
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )
    pdf.set_text_color(0, 0, 0)
    pdf.ln(6)

    # ── Clausulas ────────────────────────────────────────────────────────────
    clausulas = contract.get("clausulas") or []
    if isinstance(clausulas, list) and clausulas:
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(*_GOLD)
        pdf.cell(page_w, 8, "Clausulas", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(0, 0, 0)
        pdf.set_draw_color(*_BORDER_GRAY)

        box_top = pdf.get_y()
        pdf.set_font("Helvetica", "", 10)
        for idx, c in enumerate(clausulas, start=1):
            pdf.set_x(pdf.l_margin + 4)
            pdf.multi_cell(
                page_w - 8, 5.5, _safe_text(f"{idx}. {c}"),
                new_x=XPos.LMARGIN, new_y=YPos.NEXT,
            )
            pdf.ln(1)
        box_bottom = pdf.get_y()
        pdf.rect(pdf.l_margin, box_top - 2, page_w, box_bottom - box_top + 2)
        pdf.ln(4)

    # ── Firmas ───────────────────────────────────────────────────────────────
    if pdf.get_y() > pdf.h - 55:
        pdf.add_page()
    pdf.set_y(max(pdf.get_y(), pdf.h - 55))
    sig_w = page_w / 2 - 6
    line_y = pdf.get_y() + 18
    pdf.set_draw_color(0, 0, 0)
    pdf.line(pdf.l_margin, line_y, pdf.l_margin + sig_w, line_y)
    pdf.line(pdf.l_margin + page_w - sig_w, line_y, pdf.l_margin + page_w, line_y)
    pdf.set_y(line_y + 2)
    pdf.set_font("Helvetica", "", 9.5)
    pdf.cell(sig_w, 5, "Firma del Vendedor", align="C")
    pdf.set_x(pdf.l_margin + page_w - sig_w)
    pdf.cell(sig_w, 5, "Firma del Comprador", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # Se desactiva el salto de página automático para el pie: posicionar el
    # cursor tan cerca del borde inferior lo dispara igual, empujando este
    # texto solo a una segunda página en blanco.
    pdf.set_auto_page_break(auto=False)
    pdf.set_y(pdf.h - 15)
    pdf.set_font("Helvetica", "I", 7.5)
    pdf.set_text_color(*_MID_GRAY)
    pdf.cell(
        page_w,
        5,
        _safe_text(f"Generado por Anymotor el {datetime.now().strftime('%Y-%m-%d %H:%M')}"),
        align="C",
    )

    pdf.output(str(out))
    return str(out)

from __future__ import annotations

import os
from typing import Any

import requests


def publish_to_telegram(
    titulo: str,
    descripcion: str,
    precio: float,
    image_url: str | None = None,
    car_id: str | None = None,
    bot_token: str | None = None,
    chat_id: str | None = None,
    channel_username: str | None = None,
    bot_username: str | None = None,
) -> dict[str, Any]:
    """Publica el anuncio como un mensaje real en un chat/canal de Telegram vía Bot API.

    Si `channel_username` está configurado (canal público), el link devuelto es
    accesible por cualquiera (https://t.me/usuario/mensaje). Si no, se arma un
    link privado (solo abre si sos miembro del chat).

    Si se pasan `car_id` y hay un `bot_username` configurado, el mensaje incluye
    un botón inline que abre un chat privado con el bot para consultar/negociar
    ese auto puntual (deep link `?start=neg_<car_id>`).
    """
    token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
    chat = chat_id or os.getenv("TELEGRAM_PUBLISH_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")
    username = (channel_username or os.getenv("TELEGRAM_PUBLISH_CHANNEL_USERNAME", "")).lstrip("@")
    bot_user = (bot_username or os.getenv("TELEGRAM_BOT_USERNAME", "")).lstrip("@")

    if not token or not chat:
        return {"ok": False, "url": None, "message_id": None, "error": "Telegram no configurado"}

    text = f"🚗 *{titulo}*\n\n{descripcion}\n\n💰 *Precio:* ${precio:,.0f}"

    reply_markup = None
    if bot_user and car_id:
        deep_link = f"https://t.me/{bot_user}?start=neg_{car_id}"
        reply_markup = {
            "inline_keyboard": [[{"text": "💬 Consultar y negociar", "url": deep_link}]]
        }

    try:
        if image_url:
            url = f"https://api.telegram.org/bot{token}/sendPhoto"
            payload = {
                "chat_id": chat,
                "photo": image_url,
                "caption": text[:1024],
                "parse_mode": "Markdown",
            }
        else:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload = {"chat_id": chat, "text": text[:4096], "parse_mode": "Markdown"}
        if reply_markup:
            payload["reply_markup"] = reply_markup

        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()
        message_id = response.json()["result"]["message_id"]

        # Solo se puede armar un link real para canales/supergrupos (chat_id negativo,
        # prefijo -100) o si hay un username público configurado. Un chat privado
        # (chat_id positivo, ej. un DM con el bot) no tiene URL pública en Telegram.
        if username:
            public_url = f"https://t.me/{username}/{message_id}"
        elif str(chat).startswith("-100"):
            public_url = f"https://t.me/c/{str(chat)[4:]}/{message_id}"
        else:
            public_url = None

        return {"ok": True, "url": public_url, "message_id": message_id, "error": None}
    except Exception as e:
        return {"ok": False, "url": None, "message_id": None, "error": str(e)}

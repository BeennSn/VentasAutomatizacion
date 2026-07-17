import requests
import os


class TelegramNotifier:
    def __init__(self, bot_token: str = None, chat_id: str = None):
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")

    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def send_sale_closed_alert(self, car_data: dict, sale_data: dict) -> bool:
        if not self.is_configured():
            return False

        titulo = (
            f"{car_data.get('marca', '')} {car_data.get('modelo', '')} "
            f"{car_data.get('año', '')}"
        ).strip() or car_data.get("title", "Auto")
        precio = sale_data.get("precio_final")
        fecha_cita = sale_data.get("fecha_cita") or "por confirmar"
        nombre = sale_data.get("comprador_nombre")
        dni = sale_data.get("comprador_dni")
        correo = sale_data.get("comprador_correo")

        message = "✅ *ANYMOTOR — Venta cerrada*\n\n"
        message += f"*{titulo}*\n"
        if precio:
            message += f"💰 Precio final: ${precio:,.0f}\n"
        message += f"📅 Cita: {fecha_cita}\n"
        if nombre:
            message += f"🧑 Comprador: {nombre}\n"
        if dni:
            message += f"🪪 DNI: {dni}\n"
        if correo:
            message += f"✉️ Correo: {correo}"

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": message, "parse_mode": "Markdown"}
        try:
            response = requests.post(url, json=payload, timeout=15)
            return response.status_code == 200
        except Exception:
            return False

    def send_deal_alert(self, car_data: dict, analysis: dict) -> bool:
        if not self.bot_token or not self.chat_id:
            print("Telegram credentials not configured.")
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

        # Sanitizar el mensaje para evitar errores de Markdown
        def escape_markdown(text):
            if not text:
                return ""
            # Escapamos caracteres que suelen romper el parse_mode Markdown de Telegram
            return (
                str(text)
                .replace("_", "\\_")
                .replace("*", "\\*")
                .replace("`", "\\`")
                .replace("[", "\\[")
            )

        message = "🚗 *NUEVA BUENA OFERTA ENCONTRADA*\n\n"
        message += f"📌 *Título:* {escape_markdown(car_data.get('title'))}\n"
        message += f"💰 *Precio Publicado:* {escape_markdown(car_data.get('price'))}\n"
        message += f"📊 *Precio Mercado (estimado):* ${analysis.get('precio_mercado_sugerido', 'N/A')}\n"
        message += f"✅ *Por qué es buena oferta:* {escape_markdown(analysis.get('observaciones', 'N/A'))}\n\n"
        message += f"🔗 *Enlace:* {car_data.get('url')}"

        payload = {"chat_id": self.chat_id, "text": message, "parse_mode": "Markdown"}

        try:
            import time

            for attempt in range(3):
                try:
                    response = requests.post(url, json=payload, timeout=15)
                    if response.status_code != 200:
                        import logging

                        logging.error(f"Telegram API Error: {response.text}")
                    response.raise_for_status()
                    return True
                except (
                    requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    ConnectionResetError,
                ) as e:
                    import logging

                    logging.warning(
                        f"Intento {attempt + 1} falló al enviar a Telegram: {e}"
                    )
                    if attempt == 2:
                        raise
                    time.sleep(2)
        except Exception as e:
            import logging

            logging.error(f"Failed to send Telegram message: {e}")
            return False

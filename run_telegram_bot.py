"""Entrypoint standalone para correr el bot de Telegram por separado de Streamlit.

Uso: python run_telegram_bot.py
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

from agents.telegram_bot_agent import TelegramBotAgent  # noqa: E402

if __name__ == "__main__":
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    groq_key = os.getenv("GROQ_API_KEY")
    allowed = os.getenv("TELEGRAM_ALLOWED_USERS", "")

    if not token or not groq_key:
        raise SystemExit("Falta TELEGRAM_BOT_TOKEN o GROQ_API_KEY en .env")

    bot = TelegramBotAgent(
        token=token,
        groq_key=groq_key,
        allowed_users=[u.strip() for u in allowed.split(",") if u.strip()],
    )
    bot.run_forever()

import asyncio
import json
import os

from http.server import BaseHTTPRequestHandler

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

import bot


def build_application():
    """Create the same Telegram application/handlers used by bot.py."""
    app = (
        Application.builder()
        .token(bot.BOT_TOKEN)
        .build()
    )

    app.add_handler(CommandHandler("start", bot.cmd_start))
    app.add_handler(CommandHandler("menu", bot.cmd_start))
    app.add_handler(CommandHandler("proxy", bot.cmd_proxy))
    app.add_handler(CallbackQueryHandler(bot.handle_callback_query))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_text_messages)
    )
    return app


async def process_telegram_update(payload):
    app = build_application()
    await app.initialize()
    await app.start()
    try:
        update = Update.de_json(payload, app.bot)
        if update is None:
            return False
        await app.process_update(update)
        return True
    finally:
        await app.stop()
        await app.shutdown()


class handler(BaseHTTPRequestHandler):
    def _send(self, status, body, content_type="application/json"):
        raw = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self._send(
            200,
            json.dumps(
                {
                    "ok": True,
                    "service": "ProRewards Telegram Bot",
                    "mode": "webhook",
                }
            ),
        )

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8"))
            asyncio.run(process_telegram_update(payload))
            self._send(200, '{"ok":true}')
        except Exception as exc:
            bot.logger.exception("Vercel webhook error: %s", exc)
            self._send(500, json.dumps({"ok": False, "error": str(exc)}))


if __name__ == "__main__":
    pass

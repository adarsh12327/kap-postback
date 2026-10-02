import asyncio
import json
import os
from http.server import BaseHTTPRequestHandler
from urllib.request import Request, urlopen

_app = None
_initialized = False
_bot = None


def get_bot():
    global _bot
    if _bot is None:
        import bot
        _bot = bot
    return _bot


def build_application():
    bot = get_bot()
    from telegram.ext import (
        Application,
        CallbackQueryHandler,
        CommandHandler,
        MessageHandler,
        filters,
    )

    app = Application.builder().token(bot.BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", bot.cmd_start))
    app.add_handler(CommandHandler("menu", bot.cmd_start))
    app.add_handler(CommandHandler("proxy", bot.cmd_proxy))
    app.add_handler(CallbackQueryHandler(bot.handle_callback_query))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_text_messages)
    )
    return app


async def get_app():
    global _app, _initialized
    if _app is None:
        _app = build_application()
    if not _initialized:
        await _app.initialize()
        _initialized = True
    return _app


def set_webhook():
    bot = get_bot()
    token = bot.BOT_TOKEN
    base = os.getenv("VERCEL_URL", "").strip() or "kap-postback.vercel.app"
    if not token:
        return {"ok": False, "message": "BOT_TOKEN is not configured"}

    webhook_url = "https://" + base + "/api/index"
    url = "https://api.telegram.org/bot" + token + "/setWebhook"
    body = json.dumps({"url": webhook_url}).encode("utf-8")
    req = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


async def process_update(payload):
    from telegram import Update

    bot = get_bot()
    app = await get_app()
    update = Update.de_json(payload, app.bot)
    if update is None:
        return False
    await app.process_update(update)
    return True


class handler(BaseHTTPRequestHandler):
    def _send(self, status, body):
        raw = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        try:
            bot = get_bot()
            token_configured = bool(bot.BOT_TOKEN)
            webhook_result = None

            if token_configured:
                try:
                    webhook_result = set_webhook()
                except Exception as exc:
                    bot.logger.warning("Webhook setup failed: %s", exc)
                    webhook_result = {"ok": False, "error": str(exc)[:300]}

            self._send(
                200,
                json.dumps(
                    {
                        "ok": True,
                        "service": "kap-postback",
                        "mode": "webhook",
                        "bot_token_configured": token_configured,
                        "webhook": webhook_result,
                    }
                ),
            )
        except Exception as exc:
            self._send(
                500,
                json.dumps(
                    {
                        "ok": False,
                        "service": "kap-postback",
                        "error": str(exc)[:500],
                    }
                ),
            )

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            asyncio.run(process_update(payload))
            self._send(200, '{"ok":true}')
        except Exception as exc:
            try:
                get_bot().logger.exception("Vercel webhook error: %s", exc)
            except Exception:
                pass
            self._send(
                500,
                json.dumps({"ok": False, "error": str(exc)[:500]}),
            )


if __name__ == "__main__":
    pass

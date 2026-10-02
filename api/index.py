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

    # Vercel invocations may use different event loops. Do not keep an
    # asyncio-bound PTB Application across asyncio.run() calls.
    bot = get_bot()
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
    def _send(self, status, body):
        raw = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        # Keep the health check independent of bot.py so import/runtime
        # problems can be diagnosed without turning the health endpoint into
        # the same failing function.
        if self.path.split("?", 1)[0] in ("/", "/api/index"):
            try:
                result = {
                    "ok": True,
                    "service": "kap-postback",
                    "mode": "webhook",
                    "python_function": "ready",
                }

                if "setup=1" in self.path:
                    try:
                        webhook_result = set_webhook()
                        result["webhook"] = webhook_result
                    except Exception as exc:
                        result["webhook"] = {
                            "ok": False,
                            "error": str(exc)[:500],
                        }

                if "diag=1" in self.path:
                    try:
                        bot = get_bot()
                        token = bot.BOT_TOKEN
                        if token:
                            with urlopen(
                                Request(
                                    "https://api.telegram.org/bot" + token + "/getWebhookInfo",
                                    method="GET",
                                ),
                                timeout=10,
                            ) as response:
                                result["telegram_webhook_info"] = json.loads(
                                    response.read().decode("utf-8")
                                )
                            with urlopen(
                                Request(
                                    "https://api.telegram.org/bot" + token + "/getMe",
                                    method="GET",
                                ),
                                timeout=10,
                            ) as response:
                                result["telegram_bot_info"] = json.loads(
                                    response.read().decode("utf-8")
                                )
                        else:
                            result["telegram_error"] = "BOT_TOKEN is not configured"
                    except Exception as exc:
                        result["telegram_error"] = str(exc)[:500]

                self._send(200, json.dumps(result))
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
            return

        self._send(404, json.dumps({"ok": False, "error": "Not found"}))

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

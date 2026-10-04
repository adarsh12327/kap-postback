import asyncio
import json
import os
from http.server import BaseHTTPRequestHandler
from urllib.request import Request, urlopen

_bot = None


def miniapp_validate(init_data):
    import hashlib, hmac, time
    from urllib.parse import parse_qsl
    token = os.getenv("BOT_TOKEN", "").strip()
    if not init_data or not token:
        raise ValueError("Telegram authentication is not configured")
    data = dict(parse_qsl(init_data, keep_blank_values=True))
    received = data.pop("hash", None)
    if not received:
        raise ValueError("Missing Telegram signature")
    stamp = int(data.get("auth_date", "0"))
    if not stamp or abs(time.time() - stamp) > 3600:
        raise ValueError("Telegram authentication expired")
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    expected = hmac.new(key, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise ValueError("Invalid Telegram signature")
    user = json.loads(data.get("user", "{}"))
    if not user.get("id"):
        raise ValueError("Telegram user missing")
    return {k: user.get(k, "") for k in ("id","first_name","last_name","username","language_code","photo_url")}


def _session_secret():
    return (os.getenv("SESSION_SECRET") or os.getenv("BOT_TOKEN") or "").strip()


def _make_kap_session(user):
    import base64, hmac, hashlib, time
    secret = _session_secret()
    if not secret:
        raise ValueError("Secure session secret is not configured")
    safe = {k: user.get(k, "") for k in ("id", "first_name", "last_name", "username", "language_code")}
    body = base64.urlsafe_b64encode(
        json.dumps({"u": safe, "exp": int(time.time()) + 86400}, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return body + "." + sig


def _read_kap_session(cookie_header):
    import base64, hmac, hashlib, time
    from http.cookies import SimpleCookie
    try:
        secret = _session_secret()
        if not secret:
            return None
        jar = SimpleCookie()
        jar.load(cookie_header or "")
        item = jar.get("kap_session")
        if not item:
            return None
        body, sig = item.value.rsplit(".", 1)
        expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return None
        raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        data = json.loads(raw.decode("utf-8"))
        if int(data.get("exp", 0)) < int(time.time()):
            return None
        return data.get("u")
    except Exception:
        return None


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
    # Replace the old bot-side credential entry point with the Web Mini App.
    # Existing bot features remain available; the old callback is intercepted.
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
    original_menu = bot.kb_main_menu
    def web_menu(user_id):
        markup = original_menu(user_id)
        rows = []
        for row in markup.inline_keyboard:
            new_row = []
            for button in row:
                if getattr(button, "callback_data", None) == "btn_login_menu":
                    new_row.append(InlineKeyboardButton("🌐 Web Login", web_app=WebAppInfo(url=bot.MINI_APP_URL)))
                else:
                    new_row.append(button)
            rows.append(new_row)
        return InlineKeyboardMarkup(rows)
    bot.kb_main_menu = web_menu

    async def web_login_callback(update, context):
        query = update.callback_query
        if not query:
            return
        await query.answer()
        await query.edit_message_text(
            "🌐 *WEB LOGIN*\\n\\n"
            "Login ab secure Web Mini App se hoga.\\n"
            "Neeche button dabakar Web Login open karein.",
            parse_mode=bot.ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🌐 Open Web Login", web_app=WebAppInfo(url=bot.MINI_APP_URL))],
                [InlineKeyboardButton("🔙 Back to Main Dashboard", callback_data="nav_main_menu")]
            ])
        )
    app.add_handler(CallbackQueryHandler(web_login_callback, pattern=r"^(btn_login_menu|login_otp)$"), group=-1)
    app.add_handler(CommandHandler("start", bot.cmd_start))
    app.add_handler(CommandHandler("menu", bot.cmd_start))
    app.add_handler(CommandHandler("proxy", bot.cmd_proxy))
    app.add_handler(CallbackQueryHandler(bot.handle_callback_query))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_text_messages)
    )
    return app


def set_webhook():
    bot = get_bot()
    token = bot.BOT_TOKEN
    # Never use VERCEL_URL here: on Vercel it can be the current
    # deployment/preview hostname, which may require deployment auth and
    # causes Telegram to receive 401 Unauthorized. Always use the public
    # production hostname for the Telegram webhook.
    base = "kap-postback.vercel.app"
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

    # A fresh Application is created for every webhook invocation. Vercel
    # may reuse a worker with a different asyncio event loop, so keeping a
    # PTB Application globally can bind it to a stale loop.
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
    def _send(self, status, body, cookie=None):
        raw = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.split("?", 1)[0] == "/api/miniapp":
            user = _read_kap_session(self.headers.get("Cookie"))
            self._send(200, json.dumps({"ok": True, "authenticated": bool(user), "user": user}))
            return
        # Serve the Web Login page directly because this project also has a
        # Python API handler that may receive the root route on Vercel.
        route = self.path.split("?", 1)[0]
        if "web=1" in self.path:
            try:
                page_path = os.path.join(os.path.dirname(__file__), "..", "index.html")
                with open(page_path, "r", encoding="utf-8") as page_file:
                    page = page_file.read()
                raw = page.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            except Exception:
                self._send(500, json.dumps({"ok": False, "error": "Web Login page unavailable"}))
            return

        if route in ("/", "/miniapp"):
            try:
                page_path = os.path.join(os.path.dirname(__file__), "..", "index.html")
                with open(page_path, "r", encoding="utf-8") as page_file:
                    page = page_file.read()
                raw = page.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            except Exception as exc:
                self._send(500, json.dumps({"ok": False, "error": "Web Login page unavailable"}))
            return

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
        if self.path.split("?", 1)[0] == "/api/miniapp":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                user = miniapp_validate(payload.get("initData", ""))
                session = _make_kap_session(user)
                self._send(
                    200,
                    json.dumps({"ok": True, "authenticated": True, "user": user}),
                    cookie=f"kap_session={session}; Path=/; Max-Age=86400; HttpOnly; Secure; SameSite=Lax",
                )
            except Exception as exc:
                self._send(401, json.dumps({"ok": False, "error": str(exc)[:160]}))
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8")
            payload = json.loads(raw)

            # Log only non-sensitive routing information. Never log the bot
            # token, JWTs, OTPs, or the complete Telegram payload.
            update_id = payload.get("update_id") if isinstance(payload, dict) else None
            update_kind = next(
                (k for k in ("message", "callback_query", "edited_message", "channel_post") if k in payload),
                "unknown",
            ) if isinstance(payload, dict) else "invalid"
            print(f"Telegram webhook received: update_id={update_id} type={update_kind}", flush=True)

            processed = asyncio.run(process_update(payload))
            print(f"Telegram webhook processed: update_id={update_id} processed={processed}", flush=True)
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

import hashlib
import hmac
import json
import os
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qsl


def validate_init_data(init_data: str, bot_token: str, max_age: int = 3600):
    if not init_data or not bot_token:
        raise ValueError("Missing Telegram init data or bot configuration")

    pairs = parse_qsl(init_data, keep_blank_values=True)
    data = dict(pairs)
    received_hash = data.pop("hash", None)
    if not received_hash:
        raise ValueError("Missing Telegram initData hash")

    auth_date = int(data.get("auth_date", "0"))
    if not auth_date or abs(time.time() - auth_date) > max_age:
        raise ValueError("Telegram initData has expired")

    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(data.items())
    )
    secret_key = hmac.new(
        b"WebAppData",
        bot_token.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    calculated = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(calculated, received_hash):
        raise ValueError("Invalid Telegram initData signature")

    user_raw = data.get("user", "{}")
    user = json.loads(user_raw)
    if not isinstance(user, dict) or not user.get("id"):
        raise ValueError("Telegram user data is missing")

    return user


class handler(BaseHTTPRequestHandler):
    def _send(self, status, payload):
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self._send(200, {"ok": True, "service": "kap-miniapp"})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            user = validate_init_data(
                payload.get("initData", ""),
                os.getenv("BOT_TOKEN", ""),
            )

            safe_user = {
                "id": user["id"],
                "first_name": user.get("first_name", ""),
                "last_name": user.get("last_name", ""),
                "username": user.get("username", ""),
                "language_code": user.get("language_code", ""),
                "photo_url": user.get("photo_url", ""),
            }
            self._send(200, {"ok": True, "user": safe_user})
        except Exception as exc:
            self._send(401, {"ok": False, "error": str(exc)[:200]})


if __name__ == "__main__":
    pass

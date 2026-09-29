import asyncio
import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, Optional

import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

BOT_TOKEN = os.getenv("BOT_TOKEN", "8041231672:AAF9lDFAQIRxWjgXHlF_6HyRa3HkhQDVFa8")
BASE_URL = "https://prorewards.io/server"
DB_FILE = os.getenv("DB_FILE", "bot_database.json")
HEADERS = {
    "accept": "application/json",
    "appversion": os.getenv("PROREWARDS_APP_VERSION", "21.4.65"),
    "fcmtoken": "null",
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 Chrome/153.0.8010.36 Mobile Safari/537.36",
}

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
log = logging.getLogger("kap-otp")
STATE: Dict[int, Dict[str, Any]] = {}

def load_db():
    if not os.path.exists(DB_FILE):
        return {"users": {}}
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {"users": {}}
    except Exception:
        return {"users": {}}

def save_db(data):
    tmp = DB_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, DB_FILE)

def get_user(uid):
    data = load_db()
    key = str(uid)
    if key not in data["users"]:
        data["users"][key] = {
            "phone": None, "country": "IN", "jwt": None,
            "name": "User", "pro_id": None, "wallet": 0,
            "joined_at": datetime.now().isoformat(timespec="seconds")
        }
        save_db(data)
    return data["users"][key]

def update_user(uid, **updates):
    data = load_db()
    key = str(uid)
    if key not in data["users"]:
        data["users"][key] = get_user(uid)
    data["users"][key].update(updates)
    save_db(data)

def make_headers(token: Optional[str] = None):
    h = dict(HEADERS)
    h["authorization"] = token or "null"
    return h

def parse_response(r):
    try:
        data = r.json()
        return data if isinstance(data, dict) else {"response": data}
    except Exception:
        return {"status": False, "message": (r.text or "")[:300]}

def get_message(data):
    for key in ("message", "msg", "error"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""

def find_token(value):
    keys = {"token", "accessToken", "access_token", "jwt", "authorization", "authToken", "auth_token"}
    if isinstance(value, dict):
        for key, item in value.items():
            if key in keys and isinstance(item, str) and item.strip():
                if item.strip().lower() not in ("null", "none"):
                    return item.strip()
            found = find_token(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = find_token(item)
            if found:
                return found
    elif isinstance(value, str):
        if re.match(r"^eyJ[\w-]+\.[\w-]+\.[\w-]+$", value.strip()):
            return value.strip()
    return None

def send_otp(phone):
    try:
        r = requests.post(
            BASE_URL + "/userLogin",
            headers=make_headers(),
            json={"number": phone, "country": "IN"},
            timeout=20,
        )
        return parse_response(r)
    except requests.RequestException as exc:
        log.error("OTP request failed: %s", exc)
        return {"status": False, "message": "ProRewards server connection failed."}

def verify_otp(phone, otp):
    try:
        r = requests.post(
            BASE_URL + "/login/finish",
            headers=make_headers(),
            json={"number": phone, "otp": otp, "country": "IN"},
            timeout=20,
        )
        data = parse_response(r)
        data["_http_status"] = r.status_code
        return data
    except requests.RequestException as exc:
        log.error("OTP verification failed: %s", exc)
        return {"status": False, "message": "Login server connection failed.", "_http_status": 0}

def check_user(jwt):
    try:
        r = requests.get(
            BASE_URL + "/checkUser",
            headers=make_headers(jwt),
            timeout=20,
        )
        if r.status_code != 200:
            return None
        return parse_response(r)
    except requests.RequestException as exc:
        log.error("checkUser failed: %s", exc)
        return None

def mask_phone(phone):
    if not phone:
        return "Not set"
    return ("*" * max(0, len(phone) - 4)) + phone[-4:]

def main_keyboard(logged_in):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Login with OTP" if logged_in else "🔐 Login with OTP", callback_data="login")],
        [
            InlineKeyboardButton("💰 My Wallet", callback_data="wallet"),
            InlineKeyboardButton("👤 My Profile", callback_data="profile")
        ],
        [InlineKeyboardButton("🚪 Logout", callback_data="logout")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")]
    ])

def cancel_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel")]])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = get_user(uid)
    logged = bool(user.get("jwt"))
    text = (
        "🤖 *KAP ProRewards Bot*\n\n"
        "🔐 Status: *%s*\n"
        "📱 Phone: %s"
    ) % ("🟢 Connected" if logged else "🔴 Not connected", mask_phone(user.get("phone")))
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=main_keyboard(logged))

async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    user = get_user(uid)
    action = query.data

    if action == "login":
        STATE[uid] = {"step": "phone"}
        await query.edit_message_text(
            "📱 *MOBILE NUMBER*\n\n"
            "ProRewards registered 10-digit mobile number bhejo.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=cancel_keyboard()
        )
        return

    if action == "cancel":
        STATE.pop(uid, None)
        await query.edit_message_text("❌ Operation cancelled.", reply_markup=main_keyboard(bool(user.get("jwt"))))
        return

    if action == "logout":
        STATE.pop(uid, None)
        update_user(uid, jwt=None, pro_id=None, name="User", wallet=0)
        await query.edit_message_text("🚪 Logged out successfully.", reply_markup=main_keyboard(False))
        return

    if action in ("profile", "wallet"):
        jwt = user.get("jwt")
        if not jwt:
            await query.edit_message_text("🔴 Pehle OTP login karo.", reply_markup=main_keyboard(False))
            return

        info = await asyncio.to_thread(check_user, jwt)
        if not info or not info.get("status"):
            update_user(uid, jwt=None, pro_id=None)
            await query.edit_message_text("❌ Session expired. Dobara login karo.", reply_markup=main_keyboard(False))
            return

        ud = info.get("userData") or {}
        name = ud.get("name") or user.get("name") or "User"
        pro_id = ud.get("_id") or user.get("pro_id")
        phone = ud.get("phoneNumber") or user.get("phone")
        wallet = info.get("wallet", user.get("wallet", 0))

        update_user(uid, name=name, pro_id=pro_id, phone=phone, wallet=wallet)

        if action == "wallet":
            text = "💰 *LIVE WALLET*\n\nBalance: %s Coins" % wallet
        else:
            text = (
                "👤 *MY PROFILE*\n\n"
                "Name: %s\nPhone: %s\nPro ID: %s\nWallet: %s Coins"
            ) % (name, mask_phone(phone), pro_id or "N/A", wallet)

        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=main_keyboard(True))
        return

    if action == "help":
        await query.edit_message_text(
            "ℹ️ *OTP LOGIN*\n\n"
            "1. Login with OTP press karo.\n"
            "2. Mobile number bhejo.\n"
            "3. Received OTP bhejo.\n"
            "4. Bot session ko checkUser se verify karega.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_keyboard(bool(user.get("jwt")))
        )

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    state = STATE.get(uid)
    if not state:
        return

    text = (update.message.text or "").strip()

    if state.get("step") == "phone":
        phone = re.sub(r"\D", "", text)
        if len(phone) != 10:
            await update.message.reply_text("❌ 10-digit mobile number bhejo.", reply_markup=cancel_keyboard())
            return

        STATE[uid] = {"step": "otp", "phone": phone}
        wait = await update.message.reply_text("📨 OTP request bhej raha hoon...")
        result = await asyncio.to_thread(send_otp, phone)

        if not result.get("status", False):
            STATE.pop(uid, None)
            await wait.edit_text(
                "❌ *OTP Send Failed*\n\n%s" % (get_message(result) or "Server rejected the request."),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_keyboard(False)
            )
            return

        await wait.edit_text(
            "✅ *OTP SENT*\n\n"
            "📱 Number: %s\n\n"
            "🔢 Ab ProRewards se mila OTP bhejo." % mask_phone(phone),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=cancel_keyboard()
        )
        return

    if state.get("step") == "otp":
        otp = re.sub(r"\D", "", text)
        phone = state.get("phone")

        if not phone:
            STATE.pop(uid, None)
            await update.message.reply_text("❌ Login session expire ho gaya.", reply_markup=main_keyboard(False))
            return

        if not 4 <= len(otp) <= 8:
            await update.message.reply_text("❌ OTP format invalid hai.", reply_markup=cancel_keyboard())
            return

        wait = await update.message.reply_text("🔐 OTP verify kar raha hoon...")
        result = await asyncio.to_thread(verify_otp, phone, otp)
        jwt = find_token(result)

        if not jwt:
            STATE.pop(uid, None)
            await wait.edit_text(
                "❌ *Login Failed*\n\n%s" %
                (get_message(result) or "OTP invalid/expired ho sakta hai ya token response me nahi mila."),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_keyboard(False)
            )
            return

        info = await asyncio.to_thread(check_user, jwt)
        if not info or not info.get("status"):
            STATE.pop(uid, None)
            await wait.edit_text(
                "⚠️ Login response mila, lekin session verification fail ho gayi.",
                reply_markup=main_keyboard(False)
            )
            return

        ud = info.get("userData") or {}
        name = ud.get("name") or "User"
        pro_id = ud.get("_id")
        live_phone = ud.get("phoneNumber") or phone
        wallet = info.get("wallet", 0)

        update_user(
            uid,
            phone=live_phone,
            country="IN",
            jwt=jwt,
            name=name,
            pro_id=pro_id,
            wallet=wallet
        )
        STATE.pop(uid, None)

        await wait.edit_text(
            "✅ *LOGIN SUCCESSFUL!*\n\n"
            "👤 Name: %s\n"
            "📱 Phone: %s\n"
            "💰 Wallet: %s Coins" % (name, mask_phone(live_phone), wallet),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_keyboard(True)
        )

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.exception("Unhandled Telegram error", exc_info=context.error)

def main():
    if not BOT_TOKEN or BOT_TOKEN == "PASTE_YOUR_BOT_TOKEN_HERE":
        raise RuntimeError("BOT_TOKEN environment variable is required.")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", start))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_error_handler(error_handler)
    log.info("KAP OTP Bot started")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

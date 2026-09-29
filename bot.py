#!/usr/bin/env python3


import asyncio
import json
import logging
import os
import random
import time
from datetime import datetime
from typing import Dict, Any, List, Tuple

import requests
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ============================================================
# LOGGING CONFIGURATION
# ============================================================
logging.basicConfig(
    format="%(asctime)s - [%(levelname)s] - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================================================
# BOT CONFIGURATION
# ============================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "PASTE_YOUR_NEW_BOT_TOKEN_HERE")
ADMIN_IDS = [7972816159]

BASE_URL = "https://prorewards.io/server"
# Confirmed ProRewards OTP send endpoint.
OTP_SEND_ENDPOINT = f"{BASE_URL}/userLogin"
OTP_FINISH_ENDPOINT = f"{BASE_URL}/login/finish"
DB_FILE = "bot_database.json"

DEFAULT_HEADERS = {
    "accept": "application/json",
    "appversion": "21.4.65",
    "fcmtoken": "dgtCWPYjTOiBhtjDK_Zzp4:APA91bGadT0Ni3q1ENqMGcNJhAiVbDYlsUMaYjytfWu3ZZBAh_NLhAsaKi-Piw8kyibidO9XJhw6aQwdNIe69wxrV9QoPGuJMQM5n5agX2KTAO11exiUGB0",
    "appinstanceid": "75f338a0914b75285c3fbd09fb14be71",
    "Content-Type": "application/json",
    "User-Agent": "okhttp/4.10.0",
}

# ============================================================
# PERSISTENT DATABASE ENGINE
# ============================================================
def load_db() -> Dict[str, Any]:
    if not os.path.exists(DB_FILE):
        initial = {
            "users": {},
            "settings": {
                "maintenance": False,
                "proxy": None,
                "total_surveys_completed": 0,
                "total_survey_coins": 0,
                "total_games_farmed": 0,
                "total_farm_coins": 0
            }
        }
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(initial, f, indent=4)
        return initial
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Database load error: {e}")
        return {
            "users": {},
            "settings": {
                "maintenance": False,
                "proxy": None,
                "total_surveys_completed": 0,
                "total_survey_coins": 0,
                "total_games_farmed": 0,
                "total_farm_coins": 0
            }
        }

def save_db(data: Dict[str, Any]):
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Database save error: {e}")

USER_STATE: Dict[int, Dict[str, Any]] = {}
RUNNING_SURVEY: Dict[int, bool] = {}
RUNNING_FARM: Dict[int, bool] = {}

def get_user_record(user_id: int) -> Dict[str, Any]:
    db = load_db()
    uid = str(user_id)
    if uid not in db["users"]:
        db["users"][uid] = {
            "jwt": None,
            "name": "User",
            "pro_id": None,
            "wallet": 0,
            "banned": False,
            "joined_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "surveys_run": 0,
            "survey_coins": 0,
            "games_farmed": 0,
            "farm_coins": 0,
            "auto_farm_enabled": False,
            "auto_farm_hour": None,
            "auto_farm_minute": None,
            "last_auto_farm_date": None,
            "auto_farm_chat": user_id
        }
        save_db(db)
    return db["users"][uid]

def update_user_record(user_id: int, updates: Dict[str, Any]):
    db = load_db()
    uid = str(user_id)
    if uid not in db["users"]:
        get_user_record(user_id)
        db = load_db()
    db["users"][uid].update(updates)
    save_db(db)

# ============================================================
# SAFE JSON PARSER & HEADERS
# ============================================================
def safe_parse_json(r: requests.Response) -> Dict[str, Any]:
    if r is None:
        return {"status": False, "message": "Server se koi response nahi mila."}

    raw_text = r.text.strip() if r.text else ""
    if not raw_text:
        return {
            "status": False,
            "message": f"Server ne khali response bheja (HTTP {r.status_code})."
        }
    try:
        data = r.json()
        if isinstance(data, dict):
            return data
        return {"status": True, "response": data}
    except Exception:
        preview = raw_text.replace("\n", " ").strip()[:120]
        return {
            "status": False,
            "message": f"Server response error (HTTP {r.status_code}): {preview}"
        }

def build_headers(jwt_token: str = None) -> Dict[str, str]:
    h = DEFAULT_HEADERS.copy()
    if jwt_token:
        h["authorization"] = jwt_token
    return h

def get_configured_proxies():
    db = load_db()
    proxy = db.get("settings", {}).get("proxy")
    if proxy:
        return {"http": proxy, "https": proxy}
    return None

# ============================================================
# PROREWARDS API WRAPPERS
# ============================================================
def api_send_otp(phone: str, country: str = "IN"):
    """Send an OTP to the user's own ProRewards account."""
    try:
        payload = {"number": phone, "country": country}
        r = requests.post(
            OTP_SEND_ENDPOINT,
            headers=build_headers(),
            json=payload,
            proxies=get_configured_proxies(),
            timeout=20
        )
        return safe_parse_json(r)
    except Exception as e:
        logger.error(f"api_send_otp error: {e}")
        return {"status": False, "message": str(e)}

def _extract_jwt(data):
    """Find a JWT/access token in common response shapes."""
    if not isinstance(data, dict):
        return None
    keys = ("token", "jwt", "accessToken", "access_token", "authorization")
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for key in ("response", "data", "result", "userData"):
        value = data.get(key)
        token = _extract_jwt(value) if isinstance(value, dict) else None
        if token:
            return token
    return None

def api_finish_otp(phone: str, otp: str, country: str = "IN"):
    """Verify OTP and return the API response plus any returned JWT."""
    try:
        payload = {"number": phone, "otp": otp, "country": country}
        r = requests.post(
            OTP_FINISH_ENDPOINT,
            headers=build_headers(),
            json=payload,
            proxies=get_configured_proxies(),
            timeout=20
        )
        data = safe_parse_json(r)
        return data, _extract_jwt(data)
    except Exception as e:
        logger.error(f"api_finish_otp error: {e}")
        return {"status": False, "message": str(e)}, None

def api_check_user(jwt_token: str):
    try:
        url = f"{BASE_URL}/checkUser"
        headers = build_headers(jwt_token)
        r = requests.get(url, headers=headers, proxies=get_configured_proxies(), timeout=15)
        if r.status_code == 200:
            return safe_parse_json(r)
    except Exception as e:
        logger.error(f"api_check_user error: {e}")
    return None

def api_fetch_nudge(jwt_token: str):
    try:
        url = f"{BASE_URL}/user/nudge"
        headers = build_headers(jwt_token)
        r = requests.get(url, headers=headers, proxies=get_configured_proxies(), timeout=15)
        if r.status_code in (200, 201):
            return safe_parse_json(r)
    except Exception as e:
        logger.error(f"api_fetch_nudge error: {e}")
    return None

def api_fetch_survey(jwt_token: str, survey_id: str):
    try:
        url = f"{BASE_URL}/user/universal/survey/{survey_id}"
        headers = build_headers(jwt_token)
        r = requests.get(url, headers=headers, proxies=get_configured_proxies(), timeout=15)
        if r.status_code in (200, 201):
            return safe_parse_json(r)
    except Exception as e:
        logger.error(f"api_fetch_survey error: {e}")
    return None

def api_submit_survey(jwt_token: str, survey_id: str, survey_type: str, question_data: list):
    try:
        url = f"{BASE_URL}/user/survey/submission"
        payload = {
            "surveyId": survey_id,
            "surveyType": survey_type,
            "questionData": question_data
        }
        headers = build_headers(jwt_token)
        r = requests.post(url, headers=headers, json=payload, proxies=get_configured_proxies(), timeout=20)
        return safe_parse_json(r)
    except Exception as e:
        logger.error(f"api_submit_survey error: {e}")
        return {"status": False, "message": str(e)}

def api_get_offers(jwt_token: str) -> List[Tuple[str, str]]:
    out = []
    try:
        url = f"{BASE_URL}/user/allOffer/GameZop/0/15"
        headers = build_headers(jwt_token)
        r = requests.get(url, headers=headers, proxies=get_configured_proxies(), timeout=15)
        if r.status_code in (200, 201):
            data = safe_parse_json(r)
            items = data.get("response", []) if isinstance(data, dict) else []
            for item in items or []:
                if isinstance(item, dict) and "_id" in item:
                    oid = item["_id"]
                    if len(oid) == 24 and oid not in [x[0] for x in out]:
                        out.append((oid, item.get("name", "Unknown Game")))
    except Exception as e:
        logger.error(f"api_get_offers error: {e}")
    return out

def api_claim_game(jwt_token: str, user_id_str: str, offer_id: str):
    payload = {"userId": user_id_str, "offerId": offer_id, "minPlayed": 1, "counting": 3}
    try:
        url = f"{BASE_URL}/gameZop/postBack"
        headers = build_headers(jwt_token)
        r = requests.post(url, headers=headers, json=payload, proxies=get_configured_proxies(), timeout=20)
        return r.status_code, r.text
    except Exception as e:
        return None, str(e)

# ============================================================
# KEYBOARD BUILDERS (100% INLINE BUTTON INTERFACES)
# ============================================================
def kb_main_menu(user_id: int) -> InlineKeyboardMarkup:
    u = get_user_record(user_id)
    has_jwt = bool(u.get("jwt"))
    login_btn_text = "🔄 Login with OTP" if has_jwt else "🔐 Login with OTP"

    keyboard = [
        [
            InlineKeyboardButton("⚡ Auto Profiler Survey", callback_data="btn_survey_menu"),
            InlineKeyboardButton("🎮 GameZop Auto Farm", callback_data="btn_farm_menu")
        ],
        [
            InlineKeyboardButton("💰 My Wallet", callback_data="btn_wallet"),
            InlineKeyboardButton("📋 View Offers", callback_data="btn_view_offers")
        ],
        [
            InlineKeyboardButton(login_btn_text, callback_data="btn_login_menu"),
            InlineKeyboardButton("⏰ Auto Daily Schedule", callback_data="btn_schedule_menu")
        ],
        [
            InlineKeyboardButton("📊 My Analytics", callback_data="btn_user_stats"),
            InlineKeyboardButton("ℹ️ Help & Guide", callback_data="btn_help")
        ]
    ]

    if user_id in ADMIN_IDS:
        keyboard.append([InlineKeyboardButton("👑 Admin Control Panel", callback_data="btn_admin_menu")])

    return InlineKeyboardMarkup(keyboard)

def kb_login_options() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 Login with OTP", callback_data="login_otp")],
        [InlineKeyboardButton("🚪 Logout Current Session", callback_data="login_logout")],
        [InlineKeyboardButton("🔙 Back to Main Dashboard", callback_data="nav_main_menu")]
    ])

def kb_survey_control(is_running: bool) -> InlineKeyboardMarkup:
    if is_running:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("⏹ Stop Auto Profiler", callback_data="survey_stop")],
            [InlineKeyboardButton("🔄 Refresh Status", callback_data="btn_survey_menu")]
        ])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Launch Auto Profiler", callback_data="survey_start")],
        [InlineKeyboardButton("🔙 Back to Main Dashboard", callback_data="nav_main_menu")]
    ])

def kb_farm_control(is_running: bool) -> InlineKeyboardMarkup:
    if is_running:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("⏹ Stop Auto Farm", callback_data="farm_stop")],
            [InlineKeyboardButton("🔄 Refresh Status", callback_data="btn_farm_menu")]
        ])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Start Game Farm Now", callback_data="farm_start")],
        [InlineKeyboardButton("📋 View Game Offers", callback_data="btn_view_offers")],
        [InlineKeyboardButton("⏰ Set Daily Schedule", callback_data="btn_schedule_menu")],
        [InlineKeyboardButton("🔙 Back to Main Dashboard", callback_data="nav_main_menu")]
    ])

def kb_schedule_menu(enabled: bool) -> InlineKeyboardMarkup:
    toggle_text = "🔴 Disable Auto Schedule" if enabled else "🟢 Enable Auto Schedule"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(toggle_text, callback_data="sched_toggle")],
        [
            InlineKeyboardButton("🌅 08:00 AM", callback_data="sched_set_08_00"),
            InlineKeyboardButton("☀️ 12:00 PM", callback_data="sched_set_12_00")
        ],
        [
            InlineKeyboardButton("🌆 06:00 PM", callback_data="sched_set_18_00"),
            InlineKeyboardButton("🌙 10:00 PM", callback_data="sched_set_22_00")
        ],
        [InlineKeyboardButton("⌨️ Enter Custom Time (HH:MM)", callback_data="sched_custom")],
        [InlineKeyboardButton("🔙 Back to Farm Menu", callback_data="btn_farm_menu")]
    ])

def kb_cancel_input() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel Operation", callback_data="cancel_action")]
    ])

def kb_admin_panel(maintenance: bool) -> InlineKeyboardMarkup:
    maint_btn_text = "🟢 Maintenance: ON (Turn OFF)" if maintenance else "🔴 Maintenance: OFF (Turn ON)"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📢 Broadcast Message", callback_data="admin_broadcast"),
            InlineKeyboardButton("👥 User Explorer", callback_data="admin_users")
        ],
        [
            InlineKeyboardButton("🌐 Set Custom Proxy", callback_data="admin_set_proxy"),
            InlineKeyboardButton(maint_btn_text, callback_data="admin_toggle_maint")
        ],
        [
            InlineKeyboardButton("🔄 Refresh Statistics", callback_data="btn_admin_menu"),
            InlineKeyboardButton("🔙 Exit to Main Dashboard", callback_data="nav_main_menu")
        ]
    ])

def kb_back_to_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back to Main Dashboard", callback_data="nav_main_menu")]
    ])

def kb_back_to_farm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back to Farm Menu", callback_data="btn_farm_menu")]
    ])

def kb_back_to_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="btn_admin_menu")]
    ])

# ============================================================
# ASYNCHRONOUS TASK 1: AUTO PROFILER SURVEY ENGINE
# ============================================================
async def run_auto_profiler_task(user_id: int, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    u = get_user_record(user_id)
    jwt_token = u.get("jwt")

    if not jwt_token:
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ *Login Required*: Kripya pehle Login karein.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_login_options()
        )
        RUNNING_SURVEY[user_id] = False
        return

    RUNNING_SURVEY[user_id] = True

    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text="⚡ *Auto Profiler Survey Engine Started*\n🔍 *Checking available profilers in Nudge...*",
        parse_mode=ParseMode.MARKDOWN
    )

    try:
        nudge_resp = await asyncio.to_thread(api_fetch_nudge, jwt_token)

        if not nudge_resp or not nudge_resp.get("status") or not nudge_resp.get("nudge", {}).get("show"):
            await status_msg.edit_text(
                "❌ *Koi Profiler Survey Available Nahi Hai!*\n\n"
                "ProRewards server par filhal koi new survey nudge nahi mila. Baad me dubara check karein.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_back_to_main()
            )
            RUNNING_SURVEY[user_id] = False
            return

        survey_info = nudge_resp.get("nudge", {}).get("survey", {})
        current_survey_id = survey_info.get("surveyId")
        survey_type = survey_info.get("surveyType", "other_profiler")
        survey_name = survey_info.get("name", "Profiler Survey")
        payout = survey_info.get("payout", 0)

        await status_msg.edit_text(
            f"🎯 *Survey Found:*\n"
            f"📋 *Name:* `{survey_name}`\n"
            f"💰 *Estimated Reward:* `{payout} Coins`\n"
            f"🆔 *Survey ID:* `{current_survey_id}`\n\n"
            f"⏳ *Auto answering questions in progress...*",
            parse_mode=ParseMode.MARKDOWN
        )

        completed_surveys_count = 0
        total_coins_earned = 0

        while current_survey_id and RUNNING_SURVEY.get(user_id, False):
            survey_data_resp = await asyncio.to_thread(api_fetch_survey, jwt_token, current_survey_id)

            if not survey_data_resp or not survey_data_resp.get("status"):
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"⚠️ *Notice*: Survey ID `{current_survey_id}` fetch nahi ho saka ya expire ho gaya.",
                    parse_mode=ParseMode.MARKDOWN
                )
                break

            questions = survey_data_resp.get("response", {}).get("surveyData", {}).get("questions", [])
            if not questions:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ Is survey me koi questions nahi mile. Skipping...",
                    parse_mode=ParseMode.MARKDOWN
                )
                break

            question_payload_data = []
            for q in questions:
                q_id = q.get("_id")
                options = q.get("option", [])
                if not options:
                    continue
                selected_option = random.choice(options)
                question_payload_data.append({
                    "questionId": q_id,
                    "optionId": selected_option.get("_id"),
                    "answer": selected_option.get("value"),
                    "preCode": selected_option.get("preCode", "1")
                })

            sub_res = await asyncio.to_thread(
                api_submit_survey,
                jwt_token,
                current_survey_id,
                survey_type,
                question_payload_data
            )

            if sub_res.get("status"):
                resp_data = sub_res.get("response", {})
                reward = resp_data.get("rewardEarned", 0)
                completed_surveys_count += 1
                total_coins_earned += reward

                next_profiler = resp_data.get("nextProfiler")

                await context.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"✅ *Survey Completed Successfully!*\n"
                        f"🎉 *Coins Added:* `+{reward}`\n"
                        f"📊 *Current Session Total:* `{total_coins_earned} Coins`\n"
                        f"🔢 *Chain Index:* `#{completed_surveys_count}`"
                    ),
                    parse_mode=ParseMode.MARKDOWN
                )

                if next_profiler and next_profiler.get("surveyId"):
                    current_survey_id = next_profiler.get("surveyId")
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"⛓ *Chaining into Next Survey* (ID: `{current_survey_id}`)...\nWaiting 3s...",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    await asyncio.sleep(3)
                else:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="🏁 *Profiler Chain Finished!* Saare chain surveys successfully claim ho gaye.",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    break
            else:
                err_msg = sub_res.get("message", "Unknown Error")
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ *Submission Failed*: `{err_msg}`",
                    parse_mode=ParseMode.MARKDOWN
                )
                break

        check_user_resp = await asyncio.to_thread(api_check_user, jwt_token)
        final_wallet = check_user_resp.get("wallet", u.get("wallet", 0)) if check_user_resp else u.get("wallet", 0)

        update_user_record(user_id, {
            "wallet": final_wallet,
            "surveys_run": u.get("surveys_run", 0) + completed_surveys_count,
            "survey_coins": u.get("survey_coins", 0) + total_coins_earned
        })

        db = load_db()
        db["settings"]["total_surveys_completed"] = db["settings"].get("total_surveys_completed", 0) + completed_surveys_count
        db["settings"]["total_survey_coins"] = db["settings"].get("total_survey_coins", 0) + total_coins_earned
        save_db(db)

        summary_text = (
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🏆 *AUTO PROFILER SUMMARY*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ *Surveys Solved:* `{completed_surveys_count}`\n"
            f"💰 *Coins Earned:* `+{total_coins_earned} Coins`\n"
            f"💎 *Final Wallet Balance:* `{final_wallet} Coins`\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=summary_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_back_to_main()
        )

    except Exception as e:
        logger.exception("Profiler task error")
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"💥 *Profiler Task Crashed*: `{str(e)}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_back_to_main()
        )
    finally:
        RUNNING_SURVEY[user_id] = False

# ============================================================
# ASYNCHRONOUS TASK 2: GAMEZOP AUTO FARM ENGINE
# ============================================================
async def run_game_farm_task(user_id: int, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    u = get_user_record(user_id)
    jwt_token = u.get("jwt")
    pro_user_id = u.get("pro_id")

    if not jwt_token:
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ *Login Required*: Kripya pehle Login karein.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_login_options()
        )
        RUNNING_FARM[user_id] = False
        return

    if not pro_user_id:
        user_info = await asyncio.to_thread(api_check_user, jwt_token)
        if user_info and user_info.get("status"):
            pro_user_id = user_info.get("userData", {}).get("_id")
            update_user_record(user_id, {"pro_id": pro_user_id})
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ *Invalid Session*: ProRewards User ID prapt nahi hui. Kripya naya Token enter karein.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_login_options()
            )
            RUNNING_FARM[user_id] = False
            return

    RUNNING_FARM[user_id] = True

    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text="🚀 *Initializing GameZop Farm Engine...*",
        parse_mode=ParseMode.MARKDOWN
    )

    try:
        user_info_init = await asyncio.to_thread(api_check_user, jwt_token)
        w_before = user_info_init.get("wallet", 0) if user_info_init else u.get("wallet", 0)

        await status_msg.edit_text(
            f"🚀 *Farm Engine Started*\n"
            f"💰 *Wallet Before:* `{w_before} Coins`\n"
            f"🔍 *Fetching available GameZop offers...*",
            parse_mode=ParseMode.MARKDOWN
        )

        offers = await asyncio.to_thread(api_get_offers, jwt_token)

        if not offers:
            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ *Koi offer nahi mila.* Token check karein (shayad expire ho gaya).",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_back_to_farm()
            )
            RUNNING_FARM[user_id] = False
            return

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"📋 *Total Offers Found:* `{len(offers)} games`\n⚙️ *Beginning automated gameplay & postbacks...*",
            parse_mode=ParseMode.MARKDOWN
        )

        earned = 0
        claimed_count = 0

        for i, (oid, name) in enumerate(offers):
            if not RUNNING_FARM.get(user_id, False):
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⏹ *Farm stopped by user signal.*",
                    parse_mode=ParseMode.MARKDOWN
                )
                break

            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🎮 *[{i+1}/{len(offers)}]* Playing `{name}`...",
                parse_mode=ParseMode.MARKDOWN
            )

            code, body = await asyncio.to_thread(api_claim_game, jwt_token, pro_user_id, oid)

            if code == 200:
                earned += 1
                claimed_count += 1
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"  ✅ *CLAIMED +1 Coin* (Total Session: `{earned}`)",
                    parse_mode=ParseMode.MARKDOWN
                )
            elif code == 400 and "Daily Limit" in str(body):
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="  ⛔ *Daily limit reached on GameZop.* Farm roki ja rahi hai.",
                    parse_mode=ParseMode.MARKDOWN
                )
                break
            elif code == 429:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="  ⚠️ *Rate limit hit.* Waiting 60s for cooldown...",
                    parse_mode=ParseMode.MARKDOWN
                )
                for _ in range(60):
                    if not RUNNING_FARM.get(user_id, False):
                        break
                    await asyncio.sleep(1)

                if RUNNING_FARM.get(user_id, False):
                    code2, body2 = await asyncio.to_thread(api_claim_game, jwt_token, pro_user_id, oid)
                    if code2 == 200:
                        earned += 1
                        claimed_count += 1
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=f"  ✅ *CLAIMED on retry +1* (Total Session: `{earned}`)",
                            parse_mode=ParseMode.MARKDOWN
                        )
                    else:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=f"  ❌ Retry Failed: `[{code2}]`",
                            parse_mode=ParseMode.MARKDOWN
                        )
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"  ❌ `[{code}]` {str(body)[:120]}",
                    parse_mode=ParseMode.MARKDOWN
                )

            if i < len(offers) - 1 and RUNNING_FARM.get(user_id, False):
                for _ in range(55):
                    if not RUNNING_FARM.get(user_id, False):
                        break
                    await asyncio.sleep(1)

        user_info_after = await asyncio.to_thread(api_check_user, jwt_token)
        w_after = user_info_after.get("wallet", w_before + earned) if user_info_after else (w_before + earned)

        update_user_record(user_id, {
            "wallet": w_after,
            "games_farmed": u.get("games_farmed", 0) + claimed_count,
            "farm_coins": u.get("farm_coins", 0) + earned
        })

        db = load_db()
        db["settings"]["total_games_farmed"] = db["settings"].get("total_games_farmed", 0) + claimed_count
        db["settings"]["total_farm_coins"] = db["settings"].get("total_farm_coins", 0) + earned
        save_db(db)

        farm_summary = (
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🏁 *GAMEZOP AUTO FARM COMPLETED*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 *Wallet Before:* `{w_before} Coins`\n"
            f"💎 *Wallet After:* `{w_after} Coins`\n"
            f"🎉 *Total Coins Earned:* `+{earned} Coins`\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=farm_summary,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_back_to_farm()
        )

    except Exception as e:
        logger.exception("Farm worker error")
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"💥 *Farm Worker Crashed*: `{str(e)}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_back_to_farm()
        )
    finally:
        RUNNING_FARM[user_id] = False

# ============================================================
# BACKGROUND SCHEDULER (PER-USER DAILY AUTO-FARM ENGINE)
# ============================================================
async def scheduler_loop(app: Application):
    while True:
        try:
            now = datetime.now()
            today = now.date().isoformat()
            db = load_db()

            for uid_str, uinfo in db.get("users", {}).items():
                uid = int(uid_str)
                if (
                    uinfo.get("auto_farm_enabled")
                    and uinfo.get("auto_farm_hour") is not None
                    and uinfo.get("auto_farm_minute") is not None
                    and uinfo.get("jwt")
                ):
                    h = uinfo["auto_farm_hour"]
                    m = uinfo["auto_farm_minute"]

                    if (
                        now.hour == h
                        and now.minute == m
                        and uinfo.get("last_auto_farm_date") != today
                        and not RUNNING_FARM.get(uid, False)
                    ):
                        uinfo["last_auto_farm_date"] = today
                        save_db(db)

                        chat_id = uinfo.get("auto_farm_chat", uid)
                        try:
                            await app.bot.send_message(
                                chat_id=chat_id,
                                text=f"⏰ *Daily Auto-Farm Schedule Triggered at {now.strftime('%H:%M')}!*\nFarm engine start ho raha hai...",
                                parse_mode=ParseMode.MARKDOWN
                            )
                            asyncio.create_task(run_game_farm_task(uid, chat_id, app))
                        except Exception as e:
                            logger.error(f"Scheduler dispatch error for {uid}: {e}")

            await asyncio.sleep(30)
        except Exception as e:
            logger.error(f"Global scheduler error: {e}")
            await asyncio.sleep(30)

# ============================================================
# COMMAND HANDLERS
# ============================================================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = get_user_record(user.id)

    db = load_db()
    if db["settings"].get("maintenance", False) and user.id not in ADMIN_IDS:
        await update.message.reply_text(
            "🛠 *Bot Maintenance Alert*\n\nBot abhi maintenance mode me hai. Admin jald hi ise wapas online karenge.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if u.get("banned", False):
        await update.message.reply_text("🚫 *Aapka account banned hai.* Support se sampark karein.")
        return

    welcome_text = (
        f"👋 *Namaste, {user.first_name}!*\n\n"
        f"🤖 *ProRewards Universal Farmer & Profiler Bot*\n"
        f"Fast Coins Auto Profiler aur GameZop Auto Game Farm dono integrated hain.\n\n"
        f"📌 *Session Status:* {'🟢 Logged In' if u.get('jwt') else '🔴 Not Logged In'}\n"
        f"💰 *Wallet Balance:* `{u.get('wallet', 0)} Coins`\n"
        f"⏰ *Auto Schedule:* {'🟢 ON' if u.get('auto_farm_enabled') else '🔴 OFF'}\n\n"
        f"Neeche diye gaye *Buttons* ka use karke control karein:"
    )

    await update.message.reply_text(
        text=welcome_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb_main_menu(user.id)
    )

async def cmd_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: `/proxy http://ip:port` ya `/proxy none`", parse_mode=ParseMode.MARKDOWN)
        return
    new_proxy = None if args[0].lower() == "none" else args[0]
    db = load_db()
    db["settings"]["proxy"] = new_proxy
    save_db(db)
    await update.message.reply_text(f"✅ Proxy updated to: `{new_proxy}`", parse_mode=ParseMode.MARKDOWN)

# ============================================================
# INLINE CALLBACK QUERY DISPATCHER
# ============================================================
async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    data = query.data
    u = get_user_record(user_id)

    db = load_db()
    if db["settings"].get("maintenance", False) and user_id not in ADMIN_IDS:
        await query.edit_message_text(
            "🛠 *Bot Maintenance Alert*\n\nBot abhi maintenance mode me hai.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_back_to_main()
        )
        return

    if u.get("banned", False):
        await query.edit_message_text("🚫 Aapka account banned hai.")
        return

    if data == "nav_main_menu":
        USER_STATE.pop(user_id, None)
        text = (
            f"🏠 *Main Control Dashboard*\n\n"
            f"👤 *Account:* `{u.get('name', 'User')}`\n"
            f"💰 *Coins:* `{u.get('wallet', 0)}`\n"
            f"🔑 *Status:* {'🟢 Connected' if u.get('jwt') else '🔴 Disconnected'}\n\n"
            f"Select any button to proceed:"
        )
        await query.edit_message_text(
            text=text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_main_menu(user_id)
        )

    elif data == "btn_wallet":
        jwt_token = u.get("jwt")
        if not jwt_token:
            await query.edit_message_text(
                "❌ *Aap abhi logged in nahi hain!*\nKripya pehle Login options me jaakar apna JWT Token enter karein.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_login_options()
            )
            return

        user_info = await asyncio.to_thread(api_check_user, jwt_token)
        if user_info and user_info.get("status"):
            udata = user_info.get("userData", {})
            wallet_coins = user_info.get("wallet", 0)
            daily_login = user_info.get("dailyLogin", "N/A")
            streak = user_info.get("streak", 0)

            update_user_record(user_id, {
                "wallet": wallet_coins,
                "name": udata.get("name", u.get("name")),
                "pro_id": udata.get("_id", u.get("pro_id"))
            })

            w_text = (
                "💳 *PROREWARDS WALLET & PROFILE*\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 *Name:* `{udata.get('name')}`\n"
                f"📱 *Phone:* `{udata.get('phoneNumber', 'N/A')}`\n"
                f"🆔 *Pro ID:* `{udata.get('_id')}`\n"
                f"💰 *Live Wallet Balance:* `{wallet_coins} Coins`\n"
                f"📅 *Daily Login Bonus:* `{daily_login}`\n"
                f"🔥 *Login Streak:* `{streak} Days`\n"
                "━━━━━━━━━━━━━━━━━━━━"
            )
        else:
            w_text = "⚠️ *Session Expired ya Token Invalid!*\nKripya naya JWT Token daalein."

        await query.edit_message_text(
            text=w_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_back_to_main()
        )

    elif data == "btn_view_offers":
        jwt_token = u.get("jwt")
        if not jwt_token:
            await query.edit_message_text(
                "❌ *Login Required*: Offers dekhne ke liye pehle login karein.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_login_options()
            )
            return

        offers = await asyncio.to_thread(api_get_offers, jwt_token)

        if not offers:
            await query.edit_message_text(
                "❌ *Koi offers nahi mile.* Token expire ho gaya hoga ya server empty hai.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_back_to_farm()
            )
            return

        lines = [f"{i+1}. 🎮 *{n}* (`{o[:8]}...`)" for i, (o, n) in enumerate(offers)]
        offers_msg = f"📋 *AVAILABLE GAMEZOP OFFERS ({len(offers)}):*\n\n" + "\n".join(lines)

        await query.edit_message_text(
            text=offers_msg,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_back_to_farm()
        )

    elif data == "btn_survey_menu":
        is_running = RUNNING_SURVEY.get(user_id, False)
        status_line = "🟢 Running..." if is_running else "⚪ Idle"
        text = (
            "⚡ *AUTO PROFILER SURVEY DASHBOARD*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"            "Yeh module smart answers randomly fill karke Fast Coins claim karta hai.\n\n"
            f"📡 *Survey Engine Status:* `{status_line}`\n"
            f"🎯 *Total Surveys Solved:* `{u.get('surveys_run', 0)}`\n"
            f"💰 *Coins Earned from Surveys:* `{u.get('survey_coins', 0)} Coins`\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )
        await query.edit_message_text(
            text=text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_survey_control(is_running)
        )

    elif data == "survey_start":
        if RUNNING_SURVEY.get(user_id, False):
            await query.answer("⚠️ Ek survey engine task pehle se chal raha hai!", show_alert=True)
            return
        if not u.get("jwt"):
            await query.answer("❌ Pehle login karein!", show_alert=True)
            await query.edit_message_text(
                "❌ *Login Required!* Pehle Login karein.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_login_options()
            )
            return

        RUNNING_SURVEY[user_id] = True
        await query.edit_message_text(
            "🚀 *Starting Auto Profiler Task...*\nBackground worker initialize ho chuka hai.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_survey_control(True)
        )
        asyncio.create_task(run_auto_profiler_task(user_id, query.message.chat_id, context))

    elif data == "survey_stop":
        if not RUNNING_SURVEY.get(user_id, False):
            await query.answer("Koi survey task nahi chal raha.", show_alert=True)
            return
        RUNNING_SURVEY[user_id] = False
        await query.edit_message_text(
            "🛑 *Stop signal sent to Auto Profiler.*\nRunner safely break ho jayega.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_back_to_main()
        )

    elif data == "btn_farm_menu":
        is_running = RUNNING_FARM.get(user_id, False)
        status_line = "🟢 Running..." if is_running else "⚪ Idle"
        sched_time = (
            f"{u.get('auto_farm_hour', 0):02d}:{u.get('auto_farm_minute', 0):02d}"
            if u.get("auto_farm_hour") is not None
            else "Not Set"
        )
        text = (
            "🎮 *GAMEZOP AUTO FARM DASHBOARD*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "GameZop postback engine automated offers play karta hai aur per-game coins claim karta hai.\n\n"
            f"📡 *Farm Worker Status:* `{status_line}`\n"
            f"⏰ *Daily Schedule:* `{'Enabled (' + sched_time + ')' if u.get('auto_farm_enabled') else 'Disabled'}`\n"
            f"🕹 *Games Farmed:* `{u.get('games_farmed', 0)}`\n"
            f"💰 *Coins Earned from Games:* `{u.get('farm_coins', 0)} Coins`\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )
        await query.edit_message_text(
            text=text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_farm_control(is_running)
        )

    elif data == "farm_start":
        if RUNNING_FARM.get(user_id, False):
            await query.answer("⚠️ Ek farm worker already running hai!", show_alert=True)
            return
        if not u.get("jwt"):
            await query.answer("❌ Pehle login karein!", show_alert=True)
            await query.edit_message_text(
                "❌ *Login Required!* Pehle Login karein.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_login_options()
            )
            return

        RUNNING_FARM[user_id] = True
        await query.edit_message_text(
            "🚀 *Starting GameZop Farm Engine...*\nPostback loop background me execute ho raha hai.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_farm_control(True)
        )
        asyncio.create_task(run_game_farm_task(user_id, query.message.chat_id, context))

    elif data == "farm_stop":
        if not RUNNING_FARM.get(user_id, False):
            await query.answer("Koi farm nahi chal raha.", show_alert=True)
            return
        RUNNING_FARM[user_id] = False
        await query.edit_message_text(
            "⏹ *Stop signal bheja gaya.*\nFarm safe cycle ke baad band ho jayega.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_back_to_farm()
        )

    elif data == "btn_schedule_menu":
        sched_enabled = u.get("auto_farm_enabled", False)
        h = u.get("auto_farm_hour")
        m = u.get("auto_farm_minute")
        time_str = f"{h:02d}:{m:02d}" if h is not None and m is not None else "Not Configured"

        text = (
            "⏰ *DAILY AUTO-FARM SCHEDULER*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Bot roz aapke set kiye gaye time par khud background me farm execute karega.\n\n"
            f"📌 *Status:* `{'🟢 Enabled' if sched_enabled else '🔴 Disabled'}`\n"
            f"🕒 *Current Schedule:* `{time_str}`\n"
            f"📅 *Last Auto-Run Date:* `{u.get('last_auto_farm_date') or 'Never'}`\n\n"
            "Quick preset select karein ya custom time dalein:"
        )
        await query.edit_message_text(
            text=text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_schedule_menu(sched_enabled)
        )

    elif data == "sched_toggle":
        current = u.get("auto_farm_enabled", False)
        if not current and (u.get("auto_farm_hour") is None or u.get("auto_farm_minute") is None):
            update_user_record(user_id, {"auto_farm_hour": 9, "auto_farm_minute": 0})
        new_val = not current
        update_user_record(user_id, {
            "auto_farm_enabled": new_val,
            "auto_farm_chat": query.message.chat_id
        })
        await query.answer(f"Daily Auto Farm: {'Enabled' if new_val else 'Disabled'}")
        u = get_user_record(user_id)
        time_str = f"{u.get('auto_farm_hour', 9):02d}:{u.get('auto_farm_minute', 0):02d}"
        text = (
            "⏰ *DAILY AUTO-FARM SCHEDULER*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 *Status:* `{'🟢 Enabled' if new_val else '🔴 Disabled'}`\n"
            f"🕒 *Current Schedule:* `{time_str}`\n\n"
            "Quick preset select karein ya custom time dalein:"
        )
        await query.edit_message_text(
            text=text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_schedule_menu(new_val)
        )

    elif data.startswith("sched_set_"):
        parts = data.split("_")
        h, m = int(parts[2]), int(parts[3])
        update_user_record(user_id, {
            "auto_farm_hour": h,
            "auto_farm_minute": m,
            "auto_farm_enabled": True,
            "auto_farm_chat": query.message.chat_id
        })
        await query.answer(f"Daily Farm set for {h:02d}:{m:02d}!", show_alert=True)
        text = (
            f"✅ *Daily Auto-Farm Schedule Set to {h:02d}:{m:02d}!*\n\n"
            "Bot roz is time par automatic game farming start kar dega."
        )
        await query.edit_message_text(
            text=text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_schedule_menu(True)
        )

    elif data == "sched_custom":
        USER_STATE[user_id] = {"action": "AWAIT_CUSTOM_TIME"}
        await query.edit_message_text(
            "⏰ *ENTER CUSTOM TIME*\n\n"
            "24-Hour format me time bhejo (e.g. `09:30` ya `21:45`):",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_cancel_input()
        )

    elif data == "btn_user_stats":
        stats_text = (
            "📊 *YOUR LIFETIME PERFORMANCE*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 *Account:* `{u.get('name')}`\n"
            f"🎯 *Auto Profiler Surveys:* `{u.get('surveys_run', 0)}`\n"
            f"💰 *Coins from Surveys:* `{u.get('survey_coins', 0)} Coins`\n"
            f"🕹 *Game Offers Farmed:* `{u.get('games_farmed', 0)}`\n"
            f"🎮 *Coins from Games:* `{u.get('farm_coins', 0)} Coins`\n"
            f"💎 *Total Bot Harvest:* `{u.get('survey_coins', 0) + u.get('farm_coins', 0)} Coins`\n"
            f"🕒 *Registered On:* `{u.get('joined_at')}`\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )
        await query.edit_message_text(
            text=stats_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_back_to_main()
        )

    elif data == "btn_help":
        help_text = (
            "ℹ️ *COMPLETE BOT USER MANUAL*\n\n"
            "1. *Login First*: 'Login with OTP' button daba kar apne ProRewards account ke mobile number se OTP login karein.\n"
            "2. *Auto Profiler*: Smart survey solver jo Fast Coins claim karta hai.\n"
            "3. *GameZop Auto Farm*: Sabhi active games ko 55s timing ke sath claim karta hai.\n"
            "4. *Daily Scheduler*: Rozana time set karne par bot automatic farm chalu kar deta hai."
        )
        await query.edit_message_text(
            text=help_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_back_to_main()
        )

    elif data == "btn_login_menu":
        await query.edit_message_text(
            "🔐 *PROREWARDS LOGIN*\n\n"
            "📱 OTP Login: apne account ke mobile number se login karein.\n"
            "OTP verify hone ke baad session automatically connect ho jayega.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_login_options()
        )

    elif data == "login_otp":
        USER_STATE[user_id] = {"action": "AWAIT_OTP_PHONE"}
        await query.edit_message_text(
            "📱 *OTP LOGIN*\n\n"
            "Apne ProRewards account ka mobile number bhejo.\n"
            "Example: `9000000000`\n\n"
            "⚠️ Sirf apne account ka number use karo.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_cancel_input()
        )

    elif data == "login_logout":
        update_user_record(user_id, {"jwt": None, "pro_id": None})
        await query.edit_message_text(
            "🚪 *Logged Out!* Aapka session successfully clear kar diya gaya hai.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_back_to_main()
        )

    elif data == "cancel_action":
        USER_STATE.pop(user_id, None)
        await query.edit_message_text(
            "❌ Action cancel kar diya gaya.",
            reply_markup=kb_back_to_main()
        )

    elif data == "btn_admin_menu":
        if user_id not in ADMIN_IDS:
            await query.answer("⛔ Access Denied! Sirf Admin ke liye hai.", show_alert=True)
            return

        db = load_db()
        total_users = len(db["users"])
        active_surveys = sum(1 for v in RUNNING_SURVEY.values() if v)
        active_farms = sum(1 for v in RUNNING_FARM.values() if v)
        maint = db["settings"].get("maintenance", False)
        proxy_val = db["settings"].get("proxy") or "None"
        tot_surveys = db["settings"].get("total_surveys_completed", 0)
        tot_survey_coins = db["settings"].get("total_survey_coins", 0)
        tot_games = db["settings"].get("total_games_farmed", 0)
        tot_farm_coins = db["settings"].get("total_farm_coins", 0)

        admin_text = (
            "👑 *MASTER ADMINISTRATOR PANEL*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"👥 *Total Registered Users:* `{total_users}`\n"
            f"⚡ *Live Profiler Workers:* `{active_surveys}`\n"
            f"🎮 *Live Game Farm Workers:* `{active_farms}`\n"
            f"🎯 *Global Surveys Solved:* `{tot_surveys}` (+{tot_survey_coins}c)\n"
            f"🕹 *Global Games Farmed:* `{tot_games}` (+{tot_farm_coins}c)\n"
            f"🌐 *Proxy Configured:* `{proxy_val}`\n"
            f"🛠 *Maintenance Mode:* `{'ENABLED' if maint else 'DISABLED'}`\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )
        await query.edit_message_text(
            text=admin_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_admin_panel(maint)
        )

    elif data == "admin_toggle_maint":
        if user_id not in ADMIN_IDS:
            return
        db = load_db()
        current = db["settings"].get("maintenance", False)
        db["settings"]["maintenance"] = not current
        save_db(db)
        await query.answer(f"Maintenance Mode: {not current}", show_alert=True)
        await query.edit_message_reply_markup(reply_markup=kb_admin_panel(not current))

    elif data == "admin_set_proxy":
        if user_id not in ADMIN_IDS:
            return
        USER_STATE[user_id] = {"action": "AWAIT_PROXY_URL"}
        await query.edit_message_text(
            "🌐 *ENTER PROXY URL*\n\n"
            "Format: `http://user:pass@host:port` ya `socks5://host:port`\n"
            "Proxy remove karne ke liye `none` bhejo.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_cancel_input()
        )

    elif data == "admin_broadcast":
        if user_id not in ADMIN_IDS:
            return
        USER_STATE[user_id] = {"action": "AWAIT_BROADCAST_TEXT"}
        await query.edit_message_text(
            "📢 *ENTER BROADCAST MESSAGE*\n\nSabhi users ko bhejne wala message chat me type karke bhejein:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_cancel_input()
        )

    elif data == "admin_users":
        if user_id not in ADMIN_IDS:
            return
        db = load_db()
        users_list = []
        for uid, uinfo in list(db["users"].items())[:25]:
            name = uinfo.get("name", "Unknown")
            wallet = uinfo.get("wallet", 0)
            banned = "🚫" if uinfo.get("banned") else "✅"
            has_token = "🟢" if uinfo.get("jwt") else "❌"
            users_list.append(f"{banned} {has_token} `{uid}` | {name} | {wallet}c")

        report = "👥 *REGISTERED USERS DIRECTORY (First 25)*\n\n" + "\n".join(users_list)
        await query.edit_message_text(
            text=report,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_back_to_admin()
        )

# ============================================================
# TEXT MESSAGE PROCESSOR (INPUT HANDLER)
# ============================================================
async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if user_id not in USER_STATE:
        return

    state = USER_STATE[user_id]
    action = state.get("action")

    # ---------- OTP PHONE INPUT ----------
    if action == "AWAIT_OTP_PHONE":
        phone = "".join(ch for ch in text if ch.isdigit())
        if phone.startswith("91") and len(phone) == 12:
            phone = phone[2:]
        if len(phone) != 10:
            await update.message.reply_text(
                "❌ *Invalid mobile number.*\n10-digit Indian mobile number bhejo.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_cancel_input()
            )
            return

        wait_msg = await update.message.reply_text(
            "📨 *OTP send ho raha hai...*",
            parse_mode=ParseMode.MARKDOWN
        )
        result = await asyncio.to_thread(api_send_otp, phone, "IN")

        ok = bool(result and (result.get("status") is True or result.get("success") is True))
        if ok:
            USER_STATE[user_id] = {"action": "AWAIT_OTP_CODE", "phone": phone, "country": "IN"}
            await wait_msg.edit_text(
                "✅ *OTP sent!*\n\n"
                f"📱 Number: `{phone[:2]}******{phone[-2:]}`\n"
                "🔢 Ab 6-digit OTP bhejo.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_cancel_input()
            )
        else:
            msg = result.get("message", "OTP send nahi hua.") if isinstance(result, dict) else "OTP send nahi hua."
            await wait_msg.edit_text(
                f"❌ *OTP send failed*\n\n`{str(msg)[:300]}`\n\n"
                "Agar endpoint alag hai to `PROREWARDS_OTP_SEND_ENDPOINT` set karo.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_login_options()
            )

    # ---------- OTP CODE INPUT ----------
    elif action == "AWAIT_OTP_CODE":
        otp = "".join(ch for ch in text if ch.isdigit())
        if len(otp) < 4 or len(otp) > 8:
            await update.message.reply_text(
                "❌ *Invalid OTP.* OTP dobara bhejo.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_cancel_input()
            )
            return

        phone = state.get("phone")
        country = state.get("country", "IN")
        wait_msg = await update.message.reply_text(
            "🔄 *OTP verify ho raha hai...*",
            parse_mode=ParseMode.MARKDOWN
        )

        result, jwt_token = await asyncio.to_thread(api_finish_otp, phone, otp, country)
        USER_STATE.pop(user_id, None)

        if jwt_token:
            user_info = await asyncio.to_thread(api_check_user, jwt_token)
            if user_info and user_info.get("status"):
                udata = user_info.get("userData", {})
                wallet = user_info.get("wallet", 0)
                update_user_record(user_id, {
                    "jwt": jwt_token,
                    "name": udata.get("name", "User"),
                    "pro_id": udata.get("_id"),
                    "wallet": wallet
                })
                await wait_msg.edit_text(
                    "✅ *LOGIN SUCCESSFUL!*\n\n"
                    f"👤 *Name:* `{udata.get('name', 'User')}`\n"
                    f"📱 *Phone:* `{udata.get('phoneNumber', phone)}`\n"
                    f"🆔 *Pro ID:* `{udata.get('_id', 'N/A')}`\n"
                    f"💰 *Wallet:* `{wallet} Coins`\n\n"
                    "Ab aap dashboard use kar sakte ho.",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=kb_main_menu(user_id)
                )
            else:
                await wait_msg.edit_text(
                    "⚠️ OTP verify ho gaya, lekin returned token se profile verify nahi hui.\n"
                    "Server response check karo.",
                    reply_markup=kb_login_options()
                )
        else:
            msg = result.get("message", "OTP verification failed.") if isinstance(result, dict) else "OTP verification failed."
            await wait_msg.edit_text(
                f"❌ *OTP verification failed.*\n\n`{str(msg)[:300]}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_login_options()
            )

    # ---------- CUSTOM SCHEDULE TIME INPUT ----------
    elif action == "AWAIT_CUSTOM_TIME":
        USER_STATE.pop(user_id, None)
        try:
            parts = text.split(":")
            h, m = int(parts[0]), int(parts[1])
            if not (0 <= h <= 23 and 0 <= m <= 59):
                raise ValueError
        except Exception:
            await update.message.reply_text(
                "❌ *Invalid Time Format!* Please use `HH:MM` (e.g. `14:30`).",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_back_to_farm()
            )
            return

        update_user_record(user_id, {
            "auto_farm_hour": h,
            "auto_farm_minute": m,
            "auto_farm_enabled": True,
            "auto_farm_chat": update.effective_chat.id
        })

        await update.message.reply_text(
            f"⏰ Daily auto-farm schedule set for *{h:02d}:{m:02d}*\nBot roz is time par automatic start karega.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_farm_control(False)
        )

    # ---------- ADMIN PROXY INPUT ----------
    elif action == "AWAIT_PROXY_URL":
        if user_id not in ADMIN_IDS:
            USER_STATE.pop(user_id, None)
            return

        USER_STATE.pop(user_id, None)
        new_proxy = None if text.lower() == "none" else text

        db = load_db()
        db["settings"]["proxy"] = new_proxy
        save_db(db)

        await update.message.reply_text(
            f"✅ *Proxy updated to:* `{new_proxy}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_back_to_admin()
        )

    # ---------- ADMIN BROADCAST INPUT ----------
    elif action == "AWAIT_BROADCAST_TEXT":
        if user_id not in ADMIN_IDS:
            USER_STATE.pop(user_id, None)
            return

        USER_STATE.pop(user_id, None)
        broadcast_content = text

        status_msg = await update.message.reply_text("🚀 *Broadcasting message to all users...*", parse_mode=ParseMode.MARKDOWN)
        db = load_db()
        users = list(db["users"].keys())
        sent = 0
        failed = 0

        for uid_str in users:
            try:
                await context.bot.send_message(
                    chat_id=int(uid_str),
                    text=f"📢 *OFFICIAL ANNOUNCEMENT*\n\n{broadcast_content}",
                    parse_mode=ParseMode.MARKDOWN
                )
                sent += 1
                await asyncio.sleep(0.05)
            except Exception:
                failed += 1

        await status_msg.edit_text(
            f"✅ *Broadcast Finished!*\n\n"
            f"📤 *Delivered:* `{sent}` users\n"
            f"❌ *Failed / Blocked:* `{failed}` users",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_back_to_admin()
        )

# ============================================================
# APPLICATION INITIALIZATION & STARTUP
# ============================================================
async def post_init(app: Application):
    logger.info("Initializing background scheduler...")
    asyncio.create_task(scheduler_loop(app))

def main():
    print("=" * 65)
    print("  PROREWARDS MASTER BOT - DUAL ENGINE (PROFILER + GAME FARM)")
    print("=" * 65)

    try:
        asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if BOT_TOKEN == "PASTE_YOUR_NEW_BOT_TOKEN_HERE":
        raise RuntimeError("BOT_TOKEN set karo: environment variable BOT_TOKEN me apna NEW Telegram bot token do.")

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_start))
    app.add_handler(CommandHandler("proxy", cmd_proxy))
    app.add_handler(CallbackQueryHandler(handle_callback_query))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_messages))

    print("[+] Master Bot running... Polling active.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
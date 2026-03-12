import os
import json
import time
import re
import asyncio
from pathlib import Path
from datetime import datetime, timedelta, timezone

from telegram import (
    Update,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ChatMemberStatus
from telegram.error import BadRequest, Forbidden
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

TOKEN = os.getenv("BOT_TOKEN")

DATA_FILE = Path("xp_data.json")
FLAG_LOG_FILE = Path("flagged_logs.json")
WELCOME_IMAGE = "DF37A5AF-B14A-435B-BC4F-72F03FF8D901.png"

RESET_SECONDS = 86400

# =========================
# BOT SETTINGS
# =========================
AUTO_DELETE_BOT_MESSAGES = True
AUTO_DELETE_BOT_SECONDS = 30
DELETE_USER_COMMAND_MESSAGES = True

AUTO_DELETE_FLAGGED_MESSAGES = True
AUTO_WARN_ON_AUTO_FLAG = True
AUTO_MUTE_AFTER_WARNINGS = 3
AUTO_MUTE_MINUTES = 60

COMMAND_COOLDOWNS = {
    "rank": 8,
    "profile": 8,
    "wins": 8,
    "leaderboard": 12,
    "top": 12,
    "daily": 8,
    "boss": 8,
}

FLAG_PHRASES = [
    "kids",
    "join here",
    "teens",
    "child",
    "underage",
    "buy here",
    "visit https://",
    "promo",
    "advertise",
    "sponsor",
    "paid post",
]

MAX_LINKS_BEFORE_FLAG = 2


# =========================
# FILE HELPERS
# =========================
def safe_load_json(path: Path, default):
    if not path.exists():
        return default

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        broken_name = path.with_suffix(path.suffix + ".broken")
        try:
            path.replace(broken_name)
        except Exception:
            pass
        return default


def load_data():
    data = safe_load_json(DATA_FILE, {})

    data.setdefault("users", {})
    data.setdefault("daily_start", time.time())
    data.setdefault("current_boss", None)
    data.setdefault("boss_since", None)
    data.setdefault("topics", {
        "welcome": None,
        "levels": None,
        "bot_menu": None,
    })
    data.setdefault("admin_group", None)
    data.setdefault("recent_messages", {})

    return data


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_flag_logs():
    return safe_load_json(FLAG_LOG_FILE, [])


def save_flag_logs(logs):
    with open(FLAG_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(logs, f, indent=2)


def append_flag_log(entry):
    logs = load_flag_logs()
    logs.append(entry)
    save_flag_logs(logs)


# =========================
# GENERAL HELPERS
# =========================
def xp_needed(level: int) -> int:
    return 100 + (level * 50)


def get_user(data, user):
    uid = str(user.id)

    if uid not in data["users"]:
        data["users"][uid] = {
            "name": user.full_name,
            "xp": 0,
            "level": 1,
            "messages": 0,
            "wins": 0,
            "warnings": 0,
        }

    data["users"][uid]["name"] = user.full_name
    return uid, data["users"][uid]


def format_streak(seconds):
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def time_left(data):
    elapsed = time.time() - data["daily_start"]
    remaining = max(0, RESET_SECONDS - elapsed)

    hours = int(remaining // 3600)
    minutes = int((remaining % 3600) // 60)

    return f"{hours}h {minutes}m"


def rotate_daily_if_needed(data):
    if time.time() - data["daily_start"] < RESET_SECONDS:
        return False

    ranked = sorted(
        data["users"].items(),
        key=lambda item: item[1]["messages"],
        reverse=True,
    )

    top_three = [item for item in ranked[:3] if item[1]["messages"] > 0]

    for _, record in top_three:
        record["wins"] += 1

    for record in data["users"].values():
        record["messages"] = 0

    data["daily_start"] = time.time()
    data["current_boss"] = None
    data["boss_since"] = None
    data["recent_messages"] = {}
    return True


def build_message_link(chat, message_id):
    if getattr(chat, "username", None):
        return f"https://t.me/{chat.username}/{message_id}"

    chat_id = str(chat.id)
    if chat_id.startswith("-100"):
        internal = chat_id[4:]
        return f"https://t.me/c/{internal}/{message_id}"

    return None


def extract_message_text(message):
    return message.text or message.caption or "[non-text message]"


def detect_auto_flag_reason(text):
    lowered = text.lower()

    for phrase in FLAG_PHRASES:
        if phrase in lowered:
            return f"flag phrase: {phrase}"

    link_count = len(re.findall(r"https?://|t\.me/|www\.", lowered))
    if link_count > MAX_LINKS_BEFORE_FLAG:
        return f"too many links: {link_count}"

    compact = lowered.strip()
    if compact and len(compact) <= 2 and len(set(compact)) == 1:
        return "flood spam"

    return None


def detect_repeat_spam(data, user_id: str, text: str):
    if not text or text == "[non-text message]":
        return None

    text = text.strip().lower()
    if not text:
        return None

    recent = data.setdefault("recent_messages", {})
    user_recent = recent.setdefault(user_id, {"last_text": "", "count": 0, "last_ts": 0})

    now = time.time()
    if user_recent["last_text"] == text and (now - user_recent["last_ts"]) < 120:
        user_recent["count"] += 1
    else:
        user_recent["last_text"] = text
        user_recent["count"] = 1

    user_recent["last_ts"] = now

    if user_recent["count"] >= 3:
        return f"repeated message spam ({user_recent['count']}x)"

    return None


async def safe_delete_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int):
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


async def auto_delete_later(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, seconds: int):
    await asyncio.sleep(seconds)
    await safe_delete_message(context, chat_id, message_id)


async def maybe_delete_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not DELETE_USER_COMMAND_MESSAGES or not update.message or not update.effective_chat:
        return
    await safe_delete_message(context, update.effective_chat.id, update.message.message_id)


def now_utc():
    return datetime.now(timezone.utc)


# =========================
# ADMIN HELPERS
# =========================
async def is_admin_in_chat(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int):
    member = await context.bot.get_chat_member(chat_id, user_id)
    return member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER, "administrator", "creator"]


async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or not update.effective_user:
        return False
    return await is_admin_in_chat(context, update.effective_chat.id, update.effective_user.id)


def command_allowed(context: ContextTypes.DEFAULT_TYPE, user_id: int, command_name: str):
    cooldown = COMMAND_COOLDOWNS.get(command_name)
    if not cooldown:
        return True, 0

    store = context.application.bot_data.setdefault("command_cooldowns", {})
    key = f"{user_id}:{command_name}"
    last_used = store.get(key, 0)
    now = time.time()

    if now - last_used < cooldown:
        return False, int(cooldown - (now - last_used))

    store[key] = now
    return True, 0


# =========================
# MESSAGE SENDING HELPERS
# =========================
async def send_to_saved_topic(
    context: ContextTypes.DEFAULT_TYPE,
    update: Update,
    data,
    topic_key,
    text=None,
    photo_path=None,
    caption=None,
    temp=False,
    temp_seconds=AUTO_DELETE_BOT_SECONDS,
):
    topic = data["topics"].get(topic_key)
    sent_message = None

    if topic:
        chat_id = topic["chat_id"]
        thread_id = topic["thread_id"]

        if photo_path:
            with open(photo_path, "rb") as photo:
                sent_message = await context.bot.send_photo(
                    chat_id=chat_id,
                    message_thread_id=thread_id,
                    photo=photo,
                    caption=caption,
                )
        else:
            sent_message = await context.bot.send_message(
                chat_id=chat_id,
                message_thread_id=thread_id,
                text=text,
            )
    else:
        if not update.message:
            return

        if photo_path:
            with open(photo_path, "rb") as photo:
                sent_message = await update.message.reply_photo(photo=photo, caption=caption)
        else:
            sent_message = await update.message.reply_text(text)

    if sent_message and temp and AUTO_DELETE_BOT_MESSAGES:
        asyncio.create_task(
            auto_delete_later(context, sent_message.chat_id, sent_message.message_id, temp_seconds)
        )


async def send_to_main_chat(
    context: ContextTypes.DEFAULT_TYPE,
    update: Update,
    text: str,
    temp=False,
    temp_seconds=AUTO_DELETE_BOT_SECONDS,
):
    if not update.effective_chat:
        return

    sent_message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
    )

    if temp and AUTO_DELETE_BOT_MESSAGES:
        asyncio.create_task(
            auto_delete_later(context, sent_message.chat_id, sent_message.message_id, temp_seconds)
        )


async def send_to_admin_group(
    context: ContextTypes.DEFAULT_TYPE,
    data,
    text: str,
    reply_markup=None,
):
    admin_group = data.get("admin_group")
    if not admin_group:
        return False

    await context.bot.send_message(
        chat_id=admin_group,
        text=text,
        reply_markup=reply_markup,
    )
    return True


# =========================
# FLAG / MODERATION HELPERS
# =========================
async def apply_auto_warning_and_possible_mute(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    data,
    offender,
):
    if not offender or not update.effective_chat:
        return None

    _, record = get_user(data, offender)

    if AUTO_WARN_ON_AUTO_FLAG:
        record["warnings"] += 1

    result = None
    if AUTO_WARN_ON_AUTO_FLAG:
        result = f"⚠️ {record['name']} auto-warned. Total warnings: {record['warnings']}"

    if record["warnings"] >= AUTO_MUTE_AFTER_WARNINGS:
        until = now_utc() + timedelta(minutes=AUTO_MUTE_MINUTES)
        try:
            await context.bot.restrict_chat_member(
                chat_id=update.effective_chat.id,
                user_id=offender.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until,
            )
            result = (
                f"🔇 {record['name']} auto-muted for {AUTO_MUTE_MINUTES} minutes "
                f"after reaching {record['warnings']} warnings."
            )
        except Exception:
            pass

    return result


async def log_and_alert_flag(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    data,
    reason: str,
    offender,
    message_text: str,
    source_message_id: int,
    reporter_name: str = None,
):
    chat_name = update.effective_chat.title if update.effective_chat else "Unknown Chat"
    report_time = now_utc().strftime("%Y-%m-%d %H:%M:%S UTC")

    reported_username = (
        f"@{offender.username}" if offender and offender.username else offender.full_name
    )

    message_link = None
    if update.effective_chat and source_message_id:
        message_link = build_message_link(update.effective_chat, source_message_id)

    entry = {
        "time": report_time,
        "chat": chat_name,
        "chat_id": update.effective_chat.id if update.effective_chat else None,
        "reported_user_name": offender.full_name if offender else "Unknown",
        "reported_username": reported_username,
        "reported_user_id": offender.id if offender else None,
        "reporter_name": reporter_name,
        "reason": reason,
        "message": message_text,
        "message_link": message_link,
    }
    append_flag_log(entry)

    alert = (
        "🚨 FLAGGED MESSAGE\n\n"
        f"⏰ Time: {report_time}\n"
        f"📍 Chat: {chat_name}\n\n"
    )

    if reporter_name:
        alert += f"🙋 Reporter: {reporter_name}\n"

    alert += (
        f"👤 Reported User: {reported_username}\n\n"
        f"📝 Reason: {reason}\n\n"
        f"💬 Message:\n{message_text}\n"
    )

    if message_link:
        alert += f"\n🔗 Message Link:\n{message_link}"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "Warn",
                callback_data=f"mod|warn|{update.effective_chat.id}|{offender.id}"
            ),
            InlineKeyboardButton(
                "Mute 1h",
                callback_data=f"mod|mute|{update.effective_chat.id}|{offender.id}"
            ),
            InlineKeyboardButton(
                "Ban",
                callback_data=f"mod|ban|{update.effective_chat.id}|{offender.id}"
            ),
        ]
    ])

    await send_to_admin_group(context, data, alert, reply_markup=keyboard)


# =========================
# SETUP COMMANDS
# =========================
async def setwelcometopic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    if not await is_admin(update, context):
        await send_to_saved_topic(context, update, load_data(), "bot_menu", text="Only admins can set topics.", temp=True)
        return

    if update.message.message_thread_id is None:
        await update.message.reply_text("Run this inside the Welcome topic.")
        return

    data = load_data()
    data["topics"]["welcome"] = {
        "chat_id": update.effective_chat.id,
        "thread_id": update.message.message_thread_id,
    }
    save_data(data)
    await send_to_saved_topic(context, update, data, "bot_menu", text="✅ Welcome topic saved.", temp=True)
    await maybe_delete_user_command(update, context)


async def setleveltopic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    if not await is_admin(update, context):
        await send_to_saved_topic(context, update, load_data(), "bot_menu", text="Only admins can set topics.", temp=True)
        return

    if update.message.message_thread_id is None:
        await update.message.reply_text("Run this inside the Member Levels topic.")
        return

    data = load_data()
    data["topics"]["levels"] = {
        "chat_id": update.effective_chat.id,
        "thread_id": update.message.message_thread_id,
    }
    save_data(data)
    await send_to_saved_topic(context, update, data, "bot_menu", text="✅ Member Levels topic saved.", temp=True)
    await maybe_delete_user_command(update, context)


async def setbottopic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    if not await is_admin(update, context):
        await send_to_saved_topic(context, update, load_data(), "bot_menu", text="Only admins can set topics.", temp=True)
        return

    if update.message.message_thread_id is None:
        await update.message.reply_text("Run this inside the Bot Commands topic.")
        return

    data = load_data()
    data["topics"]["bot_menu"] = {
        "chat_id": update.effective_chat.id,
        "thread_id": update.message.message_thread_id,
    }
    save_data(data)
    await send_to_saved_topic(context, update, data, "bot_menu", text="✅ Bot Commands topic saved.", temp=True)
    await maybe_delete_user_command(update, context)


async def setadmingroup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can set the admin group.")
        return

    data = load_data()
    data["admin_group"] = update.effective_chat.id
    save_data(data)

    await send_to_saved_topic(context, update, data, "bot_menu", text="✅ This chat is now the admin report group.", temp=True)
    await maybe_delete_user_command(update, context)


async def topicstatus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    data = load_data()
    topic_lines = []

    for key in ["welcome", "levels", "bot_menu"]:
        value = data["topics"].get(key)
        if value:
            topic_lines.append(f"✅ {key}: chat {value['chat_id']} / thread {value['thread_id']}")
        else:
            topic_lines.append(f"❌ {key}: not set")

    admin_group = data.get("admin_group")
    text = "⚙️ TOPIC STATUS\n\n" + "\n".join(topic_lines)
    text += f"\n\n📢 Admin group: {admin_group if admin_group else 'not set'}"

    await send_to_saved_topic(context, update, data, "bot_menu", text=text, temp=True)
    await maybe_delete_user_command(update, context)


async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    text = (
        "⚙️ REGGIE SETTINGS\n\n"
        f"Auto-delete bot messages: {'ON' if AUTO_DELETE_BOT_MESSAGES else 'OFF'}\n"
        f"Delete user command messages: {'ON' if DELETE_USER_COMMAND_MESSAGES else 'OFF'}\n"
        f"Auto-delete flagged spam: {'ON' if AUTO_DELETE_FLAGGED_MESSAGES else 'OFF'}\n"
        f"Auto-warn on auto-flag: {'ON' if AUTO_WARN_ON_AUTO_FLAG else 'OFF'}\n"
        f"Auto-mute threshold: {AUTO_MUTE_AFTER_WARNINGS} warnings\n"
        f"Auto-mute duration: {AUTO_MUTE_MINUTES} minutes\n"
        f"Bot message delete time: {AUTO_DELETE_BOT_SECONDS} seconds"
    )

    await send_to_saved_topic(context, update, load_data(), "bot_menu", text=text, temp=True)
    await maybe_delete_user_command(update, context)


# =========================
# USER COMMANDS
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    data = load_data()
    rotate_daily_if_needed(data)
    save_data(data)

    text = (
        "🎩 Strictly Club Bot Active\n\n"
        "User commands:\n"
        "/rank\n"
        "/profile\n"
        "/wins\n"
        "/leaderboard\n"
        "/top\n"
        "/daily\n"
        "/boss\n"
        "/report (reply to a message)\n\n"
        "Admin:\n"
        "/warn (reply)\n"
        "/mute <minutes> (reply)\n"
        "/ban (reply)\n"
        "/unmute (reply or user id)\n"
        "/unban <user_id>\n"
        "/warnings (reply)\n"
        "/clearwarnings (reply)\n"
        "/reset\n\n"
        "Setup:\n"
        "/setwelcometopic\n"
        "/setleveltopic\n"
        "/setbottopic\n"
        "/setadmingroup\n"
        "/topicstatus\n"
        "/settings"
    )

    await send_to_saved_topic(context, update, data, "bot_menu", text=text, temp=True)
    await maybe_delete_user_command(update, context)


async def rank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user:
        return

    allowed, wait_time = command_allowed(context, update.message.from_user.id, "rank")
    data = load_data()
    if not allowed:
        await send_to_saved_topic(context, update, data, "bot_menu", text=f"⏳ Try again in {wait_time}s.", temp=True)
        await maybe_delete_user_command(update, context)
        return

    rotate_daily_if_needed(data)
    uid, user = get_user(data, update.message.from_user)
    save_data(data)

    boss_line = ""
    if data.get("current_boss") == uid and user["messages"] > 0:
        boss_line = "👑 Boss Badge: STRICTLY BOSS\n"

    text = (
        f"👤 {user['name']}\n"
        f"{boss_line}"
        f"⭐ Level: {user['level']}\n"
        f"🔥 XP: {user['xp']}\n"
        f"💬 Messages: {user['messages']}\n"
        f"🏆 Top 3 Wins: {user['wins']}\n"
        f"⚠️ Warnings: {user['warnings']}"
    )

    await send_to_saved_topic(context, update, data, "bot_menu", text=text, temp=True)
    await maybe_delete_user_command(update, context)


async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user:
        return

    allowed, wait_time = command_allowed(context, update.message.from_user.id, "profile")
    data = load_data()
    if not allowed:
        await send_to_saved_topic(context, update, data, "bot_menu", text=f"⏳ Try again in {wait_time}s.", temp=True)
        await maybe_delete_user_command(update, context)
        return

    rotate_daily_if_needed(data)
    uid, user = get_user(data, update.message.from_user)
    save_data(data)

    is_boss_now = data.get("current_boss") == uid and user["messages"] > 0
    next_level = xp_needed(user["level"])

    lines = [
        "📊 STRICTLY PROFILE",
        "",
        f"👤 Name: {user['name']}",
    ]

    if is_boss_now:
        lines.append("👑 Boss Badge: STRICTLY BOSS")

    lines.extend([
        f"⭐ Level: {user['level']}",
        f"🔥 XP: {user['xp']} / {next_level}",
        f"💬 Messages: {user['messages']}",
        f"🏆 Top 3 Wins: {user['wins']}",
        f"⚠️ Warnings: {user['warnings']}",
    ])

    await send_to_saved_topic(context, update, data, "bot_menu", text="\n".join(lines), temp=True)
    await maybe_delete_user_command(update, context)


async def wins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user:
        return

    allowed, wait_time = command_allowed(context, update.message.from_user.id, "wins")
    data = load_data()
    if not allowed:
        await send_to_saved_topic(context, update, data, "bot_menu", text=f"⏳ Try again in {wait_time}s.", temp=True)
        await maybe_delete_user_command(update, context)
        return

    rotate_daily_if_needed(data)
    _, user = get_user(data, update.message.from_user)
    save_data(data)

    await send_to_saved_topic(
        context,
        update,
        data,
        "bot_menu",
        text=f"🏆 {user['name']} has placed Top 3 {user['wins']} times.",
        temp=True,
    )
    await maybe_delete_user_command(update, context)


async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user:
        return

    allowed, wait_time = command_allowed(context, update.message.from_user.id, "leaderboard")
    data = load_data()
    if not allowed:
        await send_to_saved_topic(context, update, data, "bot_menu", text=f"⏳ Try again in {wait_time}s.", temp=True)
        await maybe_delete_user_command(update, context)
        return

    rotate_daily_if_needed(data)
    users = list(data["users"].values())
    users.sort(key=lambda x: x["messages"], reverse=True)
    save_data(data)

    if not users:
        await send_to_saved_topic(
            context,
            update,
            data,
            "bot_menu",
            text="🏆 LEADERBOARD\n\nNo activity yet.",
            temp=True,
        )
        await maybe_delete_user_command(update, context)
        return

    text = "🏆 LEADERBOARD\n\n"
    for i, u in enumerate(users[:10], start=1):
        text += f"{i}. {u['name']} — {u['messages']} msgs\n"

    await send_to_saved_topic(context, update, data, "bot_menu", text=text, temp=True, temp_seconds=45)
    await maybe_delete_user_command(update, context)


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user:
        return
    allowed, wait_time = command_allowed(context, update.message.from_user.id, "top")
    data = load_data()
    if not allowed:
        await send_to_saved_topic(context, update, data, "bot_menu", text=f"⏳ Try again in {wait_time}s.", temp=True)
        await maybe_delete_user_command(update, context)
        return
    await leaderboard(update, context)


async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user:
        return

    allowed, wait_time = command_allowed(context, update.message.from_user.id, "daily")
    data = load_data()
    if not allowed:
        await send_to_saved_topic(context, update, data, "bot_menu", text=f"⏳ Try again in {wait_time}s.", temp=True)
        await maybe_delete_user_command(update, context)
        return

    rotate_daily_if_needed(data)
    save_data(data)

    await send_to_saved_topic(
        context,
        update,
        data,
        "bot_menu",
        text=f"⏳ Daily leaderboard resets in:\n{time_left(data)}",
        temp=True,
    )
    await maybe_delete_user_command(update, context)


async def boss(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user:
        return

    allowed, wait_time = command_allowed(context, update.message.from_user.id, "boss")
    data = load_data()
    if not allowed:
        await send_to_saved_topic(context, update, data, "bot_menu", text=f"⏳ Try again in {wait_time}s.", temp=True)
        await maybe_delete_user_command(update, context)
        return

    rotate_daily_if_needed(data)
    users = list(data["users"].values())
    save_data(data)

    if not users:
        await send_to_main_chat(context, update, "👑 STRICTLY BOSS\n\nNo one is leading yet.", temp=True)
        await maybe_delete_user_command(update, context)
        return

    users.sort(key=lambda x: x["messages"], reverse=True)
    top_user = users[0]

    if top_user["messages"] == 0:
        await send_to_main_chat(context, update, "👑 STRICTLY BOSS\n\nNo one is leading yet.", temp=True)
        await maybe_delete_user_command(update, context)
        return

    streak_text = "0s"
    boss_since = data.get("boss_since")
    if boss_since:
        streak_text = format_streak(time.time() - boss_since)

    text = (
        "👑 STRICTLY BOSS\n\n"
        f"{top_user['name']}\n\n"
        f"💬 Messages: {top_user['messages']}\n"
        f"🔥 Boss Streak: {streak_text}"
    )

    await send_to_main_chat(context, update, text, temp=True)
    await maybe_delete_user_command(update, context)


# =========================
# MODERATION COMMANDS
# =========================
async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user:
        return

    data = load_data()

    if not update.message.reply_to_message:
        await send_to_saved_topic(
            context,
            update,
            data,
            "bot_menu",
            text="Reply to a message, then use /report reason",
            temp=True,
        )
        await maybe_delete_user_command(update, context)
        return

    target_message = update.message.reply_to_message
    offender = target_message.from_user
    if not offender:
        await send_to_saved_topic(
            context,
            update,
            data,
            "bot_menu",
            text="I couldn't identify the reported user.",
            temp=True,
        )
        await maybe_delete_user_command(update, context)
        return

    reason = " ".join(context.args).strip() or "No reason given"
    reporter_name = update.message.from_user.full_name
    message_text = extract_message_text(target_message)

    await log_and_alert_flag(
        update=update,
        context=context,
        data=data,
        reason=reason,
        offender=offender,
        message_text=message_text,
        source_message_id=target_message.message_id,
        reporter_name=reporter_name,
    )

    await send_to_saved_topic(
        context,
        update,
        data,
        "bot_menu",
        text="✅ Report sent to admins.",
        temp=True,
    )
    await maybe_delete_user_command(update, context)


async def warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    data = load_data()

    if not await is_admin(update, context):
        await send_to_saved_topic(context, update, data, "bot_menu", text="Only admins can warn.", temp=True)
        await maybe_delete_user_command(update, context)
        return

    if not update.message.reply_to_message or not update.message.reply_to_message.from_user:
        await send_to_saved_topic(context, update, data, "bot_menu", text="Reply to a user's message with /warn", temp=True)
        await maybe_delete_user_command(update, context)
        return

    offender = update.message.reply_to_message.from_user
    _, user = get_user(data, offender)
    user["warnings"] += 1
    save_data(data)

    await send_to_saved_topic(
        context,
        update,
        data,
        "bot_menu",
        text=f"⚠️ {user['name']} warned. Total warnings: {user['warnings']}",
        temp=True,
    )
    await maybe_delete_user_command(update, context)


async def warnings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    data = load_data()

    if not update.message.reply_to_message or not update.message.reply_to_message.from_user:
        await send_to_saved_topic(context, update, data, "bot_menu", text="Reply to a user's message with /warnings", temp=True)
        await maybe_delete_user_command(update, context)
        return

    offender = update.message.reply_to_message.from_user
    _, user = get_user(data, offender)
    save_data(data)

    await send_to_saved_topic(
        context,
        update,
        data,
        "bot_menu",
        text=f"⚠️ {user['name']} has {user['warnings']} warnings.",
        temp=True,
    )
    await maybe_delete_user_command(update, context)


async def clearwarnings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    data = load_data()

    if not await is_admin(update, context):
        await send_to_saved_topic(context, update, data, "bot_menu", text="Only admins can clear warnings.", temp=True)
        await maybe_delete_user_command(update, context)
        return

    if not update.message.reply_to_message or not update.message.reply_to_message.from_user:
        await send_to_saved_topic(context, update, data, "bot_menu", text="Reply to a user's message with /clearwarnings", temp=True)
        await maybe_delete_user_command(update, context)
        return

    offender = update.message.reply_to_message.from_user
    _, user = get_user(data, offender)
    user["warnings"] = 0
    save_data(data)

    await send_to_saved_topic(
        context,
        update,
        data,
        "bot_menu",
        text=f"✅ Cleared warnings for {user['name']}.",
        temp=True,
    )
    await maybe_delete_user_command(update, context)


async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat:
        return

    data = load_data()

    if not await is_admin(update, context):
        await send_to_saved_topic(context, update, data, "bot_menu", text="Only admins can mute.", temp=True)
        await maybe_delete_user_command(update, context)
        return

    if not update.message.reply_to_message or not update.message.reply_to_message.from_user:
        await send_to_saved_topic(context, update, data, "bot_menu", text="Reply to a user's message with /mute 60", temp=True)
        await maybe_delete_user_command(update, context)
        return

    offender = update.message.reply_to_message.from_user

    minutes = 60
    if context.args:
        try:
            minutes = int(context.args[0])
        except ValueError:
            minutes = 60

    until = now_utc() + timedelta(minutes=minutes)

    await context.bot.restrict_chat_member(
        chat_id=update.effective_chat.id,
        user_id=offender.id,
        permissions=ChatPermissions(can_send_messages=False),
        until_date=until,
    )

    await send_to_saved_topic(
        context,
        update,
        data,
        "bot_menu",
        text=f"🔇 {offender.full_name} muted for {minutes} minutes.",
        temp=True,
    )
    await maybe_delete_user_command(update, context)


async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat:
        return

    data = load_data()

    if not await is_admin(update, context):
        await send_to_saved_topic(context, update, data, "bot_menu", text="Only admins can unmute.", temp=True)
        await maybe_delete_user_command(update, context)
        return

    offender = None
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        offender = update.message.reply_to_message.from_user

    if offender is None:
        await send_to_saved_topic(context, update, data, "bot_menu", text="Reply to a muted user's message with /unmute", temp=True)
        await maybe_delete_user_command(update, context)
        return

    await context.bot.restrict_chat_member(
        chat_id=update.effective_chat.id,
        user_id=offender.id,
        permissions=ChatPermissions(
            can_send_messages=True,
            can_send_audios=True,
            can_send_documents=True,
            can_send_photos=True,
            can_send_videos=True,
            can_send_video_notes=True,
            can_send_voice_notes=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
            can_change_info=False,
            can_invite_users=True,
            can_pin_messages=False,
            can_manage_topics=False,
        ),
    )

    await send_to_saved_topic(
        context,
        update,
        data,
        "bot_menu",
        text=f"🔊 {offender.full_name} unmuted.",
        temp=True,
    )
    await maybe_delete_user_command(update, context)


async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat:
        return

    data = load_data()

    if not await is_admin(update, context):
        await send_to_saved_topic(context, update, data, "bot_menu", text="Only admins can ban.", temp=True)
        await maybe_delete_user_command(update, context)
        return

    if not update.message.reply_to_message or not update.message.reply_to_message.from_user:
        await send_to_saved_topic(context, update, data, "bot_menu", text="Reply to a user's message with /ban", temp=True)
        await maybe_delete_user_command(update, context)
        return

    offender = update.message.reply_to_message.from_user

    await context.bot.ban_chat_member(
        chat_id=update.effective_chat.id,
        user_id=offender.id,
    )

    await send_to_saved_topic(
        context,
        update,
        data,
        "bot_menu",
        text=f"⛔ {offender.full_name} has been banned.",
        temp=True,
    )
    await maybe_delete_user_command(update, context)


async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat:
        return

    data = load_data()

    if not await is_admin(update, context):
        await send_to_saved_topic(context, update, data, "bot_menu", text="Only admins can unban.", temp=True)
        await maybe_delete_user_command(update, context)
        return

    if not context.args:
        await send_to_saved_topic(context, update, data, "bot_menu", text="Use /unban <user_id>", temp=True)
        await maybe_delete_user_command(update, context)
        return

    try:
        user_id = int(context.args[0])
    except ValueError:
        await send_to_saved_topic(context, update, data, "bot_menu", text="User ID must be a number.", temp=True)
        await maybe_delete_user_command(update, context)
        return

    try:
        await context.bot.unban_chat_member(chat_id=update.effective_chat.id, user_id=user_id, only_if_banned=True)
        await send_to_saved_topic(context, update, data, "bot_menu", text=f"✅ Unbanned user {user_id}.", temp=True)
    except Exception as e:
        await send_to_saved_topic(context, update, data, "bot_menu", text=f"Failed to unban: {e}", temp=True)

    await maybe_delete_user_command(update, context)


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    data = load_data()

    if not await is_admin(update, context):
        await send_to_saved_topic(context, update, data, "bot_menu", text="Only admins can reset.", temp=True)
        await maybe_delete_user_command(update, context)
        return

    ranked = sorted(
        data["users"].items(),
        key=lambda item: item[1]["messages"],
        reverse=True,
    )
    top_three = [item for item in ranked[:3] if item[1]["messages"] > 0]

    for _, record in top_three:
        record["wins"] += 1

    for record in data["users"].values():
        record["messages"] = 0

    data["daily_start"] = time.time()
    data["current_boss"] = None
    data["boss_since"] = None
    data["recent_messages"] = {}
    save_data(data)

    await send_to_saved_topic(context, update, data, "bot_menu", text="🔄 Leaderboard reset.", temp=True)
    await maybe_delete_user_command(update, context)


async def moderation_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return

    await query.answer()

    parts = query.data.split("|")
    if len(parts) != 4 or parts[0] != "mod":
        return

    action = parts[1]
    source_chat_id = int(parts[2])
    offender_id = int(parts[3])

    caller = query.from_user
    if not await is_admin_in_chat(context, source_chat_id, caller.id):
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("Only source chat admins can use these buttons.")
        return

    try:
        if action == "warn":
            data = load_data()
            try:
                offender_chat_member = await context.bot.get_chat_member(source_chat_id, offender_id)
                offender_user = offender_chat_member.user
                _, record = get_user(data, offender_user)
                record["warnings"] += 1
                save_data(data)
                result_text = f"⚠️ Warned {record['name']}. Total warnings: {record['warnings']}"
            except Exception:
                result_text = "⚠️ Warning added, but user details could not be refreshed."

        elif action == "mute":
            until = now_utc() + timedelta(hours=1)
            await context.bot.restrict_chat_member(
                chat_id=source_chat_id,
                user_id=offender_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until,
            )
            result_text = "🔇 User muted for 1 hour."

        elif action == "ban":
            await context.bot.ban_chat_member(
                chat_id=source_chat_id,
                user_id=offender_id,
            )
            result_text = "⛔ User banned."

        else:
            result_text = "Unknown action."

        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(result_text)

    except Exception as e:
        await query.message.reply_text(f"Action failed: {e}")


# =========================
# XP + ACTIVITY
# =========================
async def maybe_delete_flagged_source_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not AUTO_DELETE_FLAGGED_MESSAGES or not update.message or not update.effective_chat:
        return
    await safe_delete_message(context, update.effective_chat.id, update.message.message_id)


async def give_xp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user:
        return

    # Skip joins/service messages and bot commands
    if update.message.new_chat_members:
        return
    if update.message.text and update.message.text.startswith("/"):
        return

    data = load_data()
    rotate_daily_if_needed(data)
    uid, user = get_user(data, update.message.from_user)

    text = extract_message_text(update.message)

    auto_flag_reason = detect_auto_flag_reason(text) if text != "[non-text message]" else None
    repeat_reason = detect_repeat_spam(data, uid, text)
    spam_reason = auto_flag_reason or repeat_reason

    previous_boss_id = data.get("current_boss")
    previous_boss_name = None
    if previous_boss_id and previous_boss_id in data["users"]:
        previous_boss_name = data["users"][previous_boss_id]["name"]

    user["messages"] += 1
    user["xp"] += 15

    level_ups = 0
    while user["xp"] >= xp_needed(user["level"]):
        user["xp"] -= xp_needed(user["level"])
        user["level"] += 1
        level_ups += 1

    top_user_id = None
    top_user_data = None

    for check_uid, record in data["users"].items():
        if top_user_data is None or record["messages"] > top_user_data["messages"]:
            top_user_id = check_uid
            top_user_data = record

    boss_alert_text = None
    if top_user_id:
        if previous_boss_id is None:
            data["current_boss"] = top_user_id
            data["boss_since"] = time.time()
        elif top_user_id != previous_boss_id:
            data["current_boss"] = top_user_id
            data["boss_since"] = time.time()
            boss_alert_text = (
                "🔥 NEW STRICTLY BOSS\n\n"
                f"{top_user_data['name']} just took the top spot from {previous_boss_name}.\n"
                f"💬 Messages: {top_user_data['messages']}"
            )

    save_data(data)

    if level_ups > 0:
        await send_to_saved_topic(
            context,
            update,
            data,
            "levels",
            text=f"🎉 {user['name']} reached level {user['level']}!",
            temp=False,
        )

    if boss_alert_text:
        await send_to_main_chat(context, update, boss_alert_text, temp=False)

    if spam_reason:
        await log_and_alert_flag(
            update=update,
            context=context,
            data=data,
            reason=spam_reason,
            offender=update.message.from_user,
            message_text=text,
            source_message_id=update.message.message_id,
            reporter_name=None,
        )

        auto_action_text = await apply_auto_warning_and_possible_mute(
            update=update,
            context=context,
            data=data,
            offender=update.message.from_user,
        )
        save_data(data)

        if auto_action_text:
            await send_to_saved_topic(
                context,
                update,
                data,
                "bot_menu",
                text=auto_action_text,
                temp=True,
                temp_seconds=45,
            )

        await maybe_delete_flagged_source_message(update, context)


# =========================
# WELCOME
# =========================
async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.new_chat_members:
        return

    data = load_data()
    rotate_daily_if_needed(data)
    save_data(data)

    for member in update.message.new_chat_members:
        join_time = update.message.date.strftime("%H:%M")

        caption = (
            "🎩 STRICTLY CLUB\n\n"
            f"Welcome {member.full_name}\n"
            f"🕒 Joined at {join_time}\n\n"
            "Start chatting to earn XP."
        )

        photo_exists = Path(WELCOME_IMAGE).exists()

        if photo_exists:
            await send_to_saved_topic(
                context,
                update,
                data,
                "welcome",
                photo_path=WELCOME_IMAGE,
                caption=caption,
                temp=False,
            )
        else:
            await send_to_saved_topic(
                context,
                update,
                data,
                "welcome",
                text=caption,
                temp=False,
            )


# =========================
# MAIN
# =========================
def main():
    if not TOKEN:
        raise ValueError("BOT_TOKEN is missing")

    app = Application.builder().token(TOKEN).build()

    # user commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("rank", rank))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("wins", wins))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("daily", daily))
    app.add_handler(CommandHandler("boss", boss))
    app.add_handler(CommandHandler("report", report))

    # moderation
    app.add_handler(CommandHandler("warn", warn))
    app.add_handler(CommandHandler("warnings", warnings_cmd))
    app.add_handler(CommandHandler("clearwarnings", clearwarnings))
    app.add_handler(CommandHandler("mute", mute))
    app.add_handler(CommandHandler("unmute", unmute))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("unban", unban))
    app.add_handler(CommandHandler("reset", reset))

    # setup
    app.add_handler(CommandHandler("setwelcometopic", setwelcometopic))
    app.add_handler(CommandHandler("setleveltopic", setleveltopic))
    app.add_handler(CommandHandler("setbottopic", setbottopic))
    app.add_handler(CommandHandler("setadmingroup", setadmingroup))
    app.add_handler(CommandHandler("topicstatus", topicstatus))
    app.add_handler(CommandHandler("settings", settings_cmd))

    # buttons + events
    app.add_handler(CallbackQueryHandler(moderation_button_handler, pattern=r"^mod\|"))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome))

    # XP for normal messages/media
    app.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND & ~filters.StatusUpdate.ALL,
            give_xp
        )
    )

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

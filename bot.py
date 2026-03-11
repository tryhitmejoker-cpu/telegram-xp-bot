import os
import json
import time
from pathlib import Path
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

TOKEN = os.getenv("BOT_TOKEN")
DATA_FILE = Path("xp_data.json")
WELCOME_IMAGE = "DF37A5AF-B14A-435B-BC4F-72F03FF8D901.png"

RESET_SECONDS = 86400


def load_data():
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {}

    if "users" not in data:
        data["users"] = {}
    if "daily_start" not in data:
        data["daily_start"] = time.time()
    if "current_boss" not in data:
        data["current_boss"] = None
    if "boss_since" not in data:
        data["boss_since"] = None
    if "topics" not in data:
        data["topics"] = {
            "welcome": None,
            "levels": None,
            "bot_menu": None,
        }

    return data


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def xp_needed(level):
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
    return True


async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or not update.effective_user:
        return False

    member = await context.bot.get_chat_member(
        update.effective_chat.id,
        update.effective_user.id
    )
    return member.status in ["administrator", "creator"]


async def send_to_saved_topic(
    context: ContextTypes.DEFAULT_TYPE,
    update: Update,
    data,
    topic_key,
    text=None,
    photo_path=None,
    caption=None,
):
    topic = data["topics"].get(topic_key)

    if topic:
        chat_id = topic["chat_id"]
        thread_id = topic["thread_id"]

        if photo_path:
            with open(photo_path, "rb") as photo:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    message_thread_id=thread_id,
                    photo=photo,
                    caption=caption,
                )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                message_thread_id=thread_id,
                text=text,
            )
        return

    if not update.message:
        return

    if photo_path:
        with open(photo_path, "rb") as photo:
            await update.message.reply_photo(photo=photo, caption=caption)
    else:
        await update.message.reply_text(text)


async def send_to_main_chat(
    context: ContextTypes.DEFAULT_TYPE,
    update: Update,
    text,
):
    if not update.effective_chat:
        return

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
    )


async def setwelcometopic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can set topics.")
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

    await update.message.reply_text("✅ Welcome topic saved.")


async def setleveltopic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can set topics.")
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

    await update.message.reply_text("✅ Member Levels topic saved.")


async def setbottopic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    if not await is_admin(update, context):
        await update.message.reply_text("Only admins can set topics.")
        return

    if update.message.message_thread_id is None:
        await update.message.reply_text("Run this inside the Bot Menu topic.")
        return

    data = load_data()
    data["topics"]["bot_menu"] = {
        "chat_id": update.effective_chat.id,
        "thread_id": update.message.message_thread_id,
    }
    save_data(data)

    await update.message.reply_text("✅ Bot Menu topic saved.")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    data = load_data()
    rotated = rotate_daily_if_needed(data)
    if rotated:
        save_data(data)

    text = (
        "🎩 Strictly Club Bot Active\n\n"
        "Commands:\n"
        "/rank\n"
        "/profile\n"
        "/wins\n"
        "/leaderboard\n"
        "/top\n"
        "/daily\n"
        "/boss\n"
        "/reset\n\n"
        "Admin setup:\n"
        "/setwelcometopic\n"
        "/setleveltopic\n"
        "/setbottopic"
    )

    await send_to_saved_topic(context, update, data, "bot_menu", text=text)


async def rank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user:
        return

    data = load_data()
    rotated = rotate_daily_if_needed(data)
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
        f"🏆 Top 3 Wins: {user['wins']}"
    )

    await send_to_saved_topic(context, update, data, "bot_menu", text=text)


async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user:
        return

    data = load_data()
    rotated = rotate_daily_if_needed(data)
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
    ])

    await send_to_saved_topic(
        context,
        update,
        data,
        "bot_menu",
        text="\n".join(lines),
    )


async def wins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user:
        return

    data = load_data()
    rotated = rotate_daily_if_needed(data)
    _, user = get_user(data, update.message.from_user)
    save_data(data)

    text = f"🏆 {user['name']} has placed Top 3 {user['wins']} times."
    await send_to_saved_topic(context, update, data, "bot_menu", text=text)


async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    data = load_data()
    rotated = rotate_daily_if_needed(data)
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
        )
        return

    text = "🏆 LEADERBOARD\n\n"
    for i, u in enumerate(users[:10], start=1):
        text += f"{i}. {u['name']} — {u['messages']} msgs\n"

    await send_to_saved_topic(context, update, data, "bot_menu", text=text)


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await leaderboard(update, context)


async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    data = load_data()
    rotated = rotate_daily_if_needed(data)
    save_data(data)

    text = f"⏳ Daily leaderboard resets in:\n{time_left(data)}"
    await send_to_saved_topic(context, update, data, "bot_menu", text=text)


async def boss(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    data = load_data()
    rotated = rotate_daily_if_needed(data)
    users = list(data["users"].values())
    save_data(data)

    if not users:
        await send_to_main_chat(
            context,
            update,
            "👑 STRICTLY BOSS\n\nNo one is leading yet.",
        )
        return

    users.sort(key=lambda x: x["messages"], reverse=True)
    top_user = users[0]

    if top_user["messages"] == 0:
        await send_to_main_chat(
            context,
            update,
            "👑 STRICTLY BOSS\n\nNo one is leading yet.",
        )
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

    await send_to_main_chat(context, update, text)


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    if not await is_admin(update, context):
        await send_to_saved_topic(
            context,
            update,
            load_data(),
            "bot_menu",
            text="Only admins can reset.",
        )
        return

    data = load_data()

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
    save_data(data)

    await send_to_saved_topic(
        context,
        update,
        data,
        "bot_menu",
        text="🔄 Leaderboard reset.",
    )


async def give_xp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user:
        return

    if update.message.new_chat_members:
        return

    data = load_data()
    rotated = rotate_daily_if_needed(data)
    uid, user = get_user(data, update.message.from_user)

    previous_boss_id = data.get("current_boss")
    previous_boss_name = None

    if previous_boss_id and previous_boss_id in data["users"]:
        previous_boss_name = data["users"][previous_boss_id]["name"]

    user["messages"] += 1
    user["xp"] += 15

    leveled_up = False
    if user["xp"] >= xp_needed(user["level"]):
        user["level"] += 1
        user["xp"] = 0
        leveled_up = True

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

    if leveled_up:
        await send_to_saved_topic(
            context,
            update,
            data,
            "levels",
            text=f"🎉 {user['name']} reached level {user['level']}!",
        )

    if boss_alert_text:
        await send_to_main_chat(context, update, boss_alert_text)


async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.new_chat_members:
        return

    data = load_data()
    rotated = rotate_daily_if_needed(data)
    save_data(data)

    for member in update.message.new_chat_members:
        join_time = update.message.date.strftime("%H:%M")

        caption = (
            "🎩 STRICTLY CLUB\n\n"
            f"Welcome {member.full_name}\n"
            f"🕒 Joined at {join_time}\n\n"
            "Start chatting to earn XP."
        )

        await send_to_saved_topic(
            context,
            update,
            data,
            "welcome",
            photo_path=WELCOME_IMAGE,
            caption=caption,
        )


def main():
    if not TOKEN:
        raise ValueError("BOT_TOKEN is missing")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("rank", rank))
    app.add_handler(CommandHandler("wins", wins))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("daily", daily))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("boss", boss))

    app.add_handler(CommandHandler("setwelcometopic", setwelcometopic))
    app.add_handler(CommandHandler("setleveltopic", setleveltopic))
    app.add_handler(CommandHandler("setbottopic", setbottopic))

    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, give_xp))

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

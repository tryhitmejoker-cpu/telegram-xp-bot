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
            return json.load(f)

    return {
        "users": {},
        "daily_start": time.time(),
        "current_boss": None
    }


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
            "wins": 0
        }

    data["users"][uid]["name"] = user.full_name
    return uid, data["users"][uid]


def time_left(data):
    elapsed = time.time() - data["daily_start"]
    remaining = max(0, RESET_SECONDS - elapsed)

    hours = int(remaining // 3600)
    minutes = int((remaining % 3600) // 60)

    return f"{hours}h {minutes}m"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    await update.message.reply_text(
        "🎩 Strictly Club Bot Active\n\n"
        "Send messages to gain XP.\n"
        "Use /rank to check your stats.\n"
        "Use /top or /leaderboard to see who’s leading.\n"
        "Use /boss to see who runs the chat."
    )


async def rank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user:
        return

    data = load_data()
    _, user = get_user(data, update.message.from_user)
    save_data(data)

    await update.message.reply_text(
        f"👤 {user['name']}\n"
        f"⭐ Level: {user['level']}\n"
        f"🔥 XP: {user['xp']}\n"
        f"💬 Messages: {user['messages']}\n"
        f"🏆 Top 3 Wins: {user['wins']}"
    )


async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user:
        return

    data = load_data()
    _, user = get_user(data, update.message.from_user)
    save_data(data)

    await update.message.reply_text(
        f"📊 PROFILE\n\n"
        f"👤 {user['name']}\n"
        f"⭐ Level: {user['level']}\n"
        f"🔥 XP: {user['xp']}\n"
        f"💬 Messages: {user['messages']}\n"
        f"🏆 Top 3 Wins: {user['wins']}"
    )


async def wins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user:
        return

    data = load_data()
    _, user = get_user(data, update.message.from_user)
    save_data(data)

    await update.message.reply_text(
        f"🏆 {user['name']} has placed Top 3 {user['wins']} times."
    )


async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    data = load_data()

    users = list(data["users"].values())
    users.sort(key=lambda x: x["messages"], reverse=True)

    if not users:
        await update.message.reply_text("🏆 LEADERBOARD\n\nNo activity yet.")
        return

    text = "🏆 LEADERBOARD\n\n"

    for i, u in enumerate(users[:10], start=1):
        text += f"{i}. {u['name']} — {u['messages']} msgs\n"

    await update.message.reply_text(text)


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await leaderboard(update, context)


async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    data = load_data()

    await update.message.reply_text(
        f"⏳ Daily leaderboard resets in:\n{time_left(data)}"
    )


async def boss(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    data = load_data()
    users = list(data["users"].values())

    if not users:
        await update.message.reply_text(
            "🔥 STRICTLY BOSS\n\nNo one is leading yet."
        )
        return

    users.sort(key=lambda x: x["messages"], reverse=True)
    top_user = users[0]

    if top_user["messages"] == 0:
        await update.message.reply_text(
            "🔥 STRICTLY BOSS\n\nNo one is leading yet."
        )
        return

    await update.message.reply_text(
        f"🔥 STRICTLY BOSS\n\n"
        f"{top_user['name']} is running the chat.\n\n"
        f"💬 Messages: {top_user['messages']}\n"
        f"⭐ Level: {top_user['level']}\n"
        f"🔥 XP: {top_user['xp']}"
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat or not update.effective_user:
        return

    chat_member = await context.bot.get_chat_member(
        update.effective_chat.id,
        update.effective_user.id
    )

    if chat_member.status not in ["administrator", "creator"]:
        await update.message.reply_text("Only admins can reset.")
        return

    data = load_data()

    for user in data["users"].values():
        user["messages"] = 0

    data["daily_start"] = time.time()
    data["current_boss"] = None
    save_data(data)

    await update.message.reply_text("🔄 Leaderboard reset.")


async def give_xp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user:
        return

    if update.message.new_chat_members:
        return

    data = load_data()
    uid, user = get_user(data, update.message.from_user)

    old_boss_id = data.get("current_boss")

    user["messages"] += 1
    user["xp"] += 15

    if user["xp"] >= xp_needed(user["level"]):
        user["level"] += 1
        user["xp"] = 0
        await update.message.reply_text(
            f"🎉 {user['name']} reached level {user['level']}!"
        )

    top_user_id = None
    top_user_data = None

    for check_uid, record in data["users"].items():
        if top_user_data is None or record["messages"] > top_user_data["messages"]:
            top_user_id = check_uid
            top_user_data = record

    if top_user_id and top_user_id != old_boss_id:
        data["current_boss"] = top_user_id

        if old_boss_id is not None:
            await update.message.reply_text(
                f"🔥 NEW STRICTLY BOSS\n\n"
                f"{top_user_data['name']} just took the top spot.\n"
                f"💬 Messages: {top_user_data['messages']}"
            )
        elif top_user_data["messages"] > 0:
            await update.message.reply_text(
                f"🔥 STRICTLY BOSS\n\n"
                f"{top_user_data['name']} is now leading the chat.\n"
                f"💬 Messages: {top_user_data['messages']}"
            )

    save_data(data)


async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.new_chat_members:
        return

    for member in update.message.new_chat_members:
        join_time = update.message.date.strftime("%H:%M")

        caption = (
            "🎩 STRICTLY CLUB\n\n"
            f"Welcome {member.full_name}\n"
            f"🕒 Joined at {join_time}\n\n"
            "Start chatting to earn XP."
        )

        with open(WELCOME_IMAGE, "rb") as photo:
            await update.message.reply_photo(photo=photo, caption=caption)


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

    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, give_xp))

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

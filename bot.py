import os
import json
from pathlib import Path
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

TOKEN = os.getenv("BOT_TOKEN")
DATA_FILE = Path("xp_data.json")
WELCOME_IMAGE = "DF37A5AF-B14A-435B-BC4F-72F03FF8D901.png"


def load_data():
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def xp_needed(level):
    return 100 + (level * 50)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    await update.message.reply_text(
        "🎩 Strictly Club is live.\n"
        "Send messages to gain XP.\n"
        "Use /rank to check your level."
    )


async def rank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user:
        return

    user = update.message.from_user
    data = load_data()
    uid = str(user.id)

    if uid not in data:
        data[uid] = {"name": user.full_name, "xp": 0, "level": 1}

    save_data(data)

    xp = data[uid]["xp"]
    level = data[uid]["level"]

    await update.message.reply_text(
        f"👤 {user.full_name}\n"
        f"⭐ Level: {level}\n"
        f"🔥 XP: {xp}"
    )


async def give_xp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user or update.message.new_chat_members:
        return

    user = update.message.from_user
    data = load_data()
    uid = str(user.id)

    if uid not in data:
        data[uid] = {"name": user.full_name, "xp": 0, "level": 1}
    else:
        data[uid]["name"] = user.full_name

    data[uid]["xp"] += 15

    if data[uid]["xp"] >= xp_needed(data[uid]["level"]):
        data[uid]["level"] += 1
        data[uid]["xp"] = 0
        await update.message.reply_text(
            f"🎉 {user.full_name} leveled up to Level {data[uid]['level']}!"
        )

    save_data(data)


async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.new_chat_members:
        return

    join_time = update.message.date.strftime("%H:%M")

    for user in update.message.new_chat_members:
        message = (
            "🎩 **STRICTLY CLUB**\n\n"
            f"Welcome **{user.full_name}**\n"
            f"🕒 Joined at: **{join_time}**\n\n"
            "You’re in now.\n"
            "Start chatting, earn XP, and climb the ranks."
        )

        with open(WELCOME_IMAGE, "rb") as photo:
            await update.message.reply_photo(
                photo=photo,
                caption=message,
                parse_mode="Markdown"
            )


def main():
    if not TOKEN:
        raise ValueError("BOT_TOKEN is missing")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("rank", rank))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, give_xp))

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

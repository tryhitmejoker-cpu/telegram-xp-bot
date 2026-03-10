import os
import json
from pathlib import Path
from datetime import date
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

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


def reset_daily_if_needed(data):
    today = str(date.today())
    if data.get("last_reset") != today:
        for key, value in data.items():
            if isinstance(value, dict) and "daily" in value:
                value["daily"] = 0
        data["last_reset"] = today
    return data


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    await update.message.reply_text(
        "🎩 STRICTLY CLUB\n\n"
        "XP system active.\n"
        "Send messages to gain XP.\n"
        "Use /rank to see your level.\n"
        "Use /top to see today’s top posters."
    )


async def rank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user:
        return

    user = update.message.from_user
    data = reset_daily_if_needed(load_data())
    uid = str(user.id)

    if uid not in data:
        data[uid] = {
            "name": user.full_name,
            "xp": 0,
            "level": 1,
            "daily": 0,
            "wins": 0,
        }

    save_data(data)

    xp = data[uid]["xp"]
    level = data[uid]["level"]
    daily = data[uid]["daily"]
    wins = data[uid]["wins"]

    await update.message.reply_text(
        f"👤 {user.full_name}\n"
        f"🏅 Level: {level}\n"
        f"⭐ XP: {xp}\n"
        f"💬 Daily Messages: {daily}\n"
        f"🏆 Wins: {wins}"
    )


async def wins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user:
        return

    user = update.message.from_user
    data = reset_daily_if_needed(load_data())
    uid = str(user.id)

    if uid not in data:
        data[uid] = {
            "name": user.full_name,
            "xp": 0,
            "level": 1,
            "daily": 0,
            "wins": 0,
        }

    save_data(data)

    await update.message.reply_text(
        f"🏆 {user.full_name} has {data[uid]['wins']} top 3 daily wins."
    )


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    data = reset_daily_if_needed(load_data())
    save_data(data)

    users = []
    for key, value in data.items():
        if isinstance(value, dict) and "daily" in value:
            users.append((value["name"], value["daily"]))

    users.sort(key=lambda x: x[1], reverse=True)

    if not users:
        await update.message.reply_text("🏆 Daily Top Posters\n\nNo activity yet.")
        return

    text = "🏆 Daily Top Posters\n\n"

    medals = ["🥇", "🥈", "🥉"]
    for i, user in enumerate(users[:3]):
        text += f"{medals[i]} {user[0]} — {user[1]} msgs\n"

    await update.message.reply_text(text)


async def give_xp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user:
        return

    if update.message.new_chat_members:
        return

    user = update.message.from_user
    data = reset_daily_if_needed(load_data())
    uid = str(user.id)

    if uid not in data:
        data[uid] = {
            "name": user.full_name,
            "xp": 0,
            "level": 1,
            "daily": 0,
            "wins": 0,
        }

    data[uid]["name"] = user.full_name
    data[uid]["xp"] += 15
    data[uid]["daily"] += 1

    if data[uid]["xp"] >= xp_needed(data[uid]["level"]):
        data[uid]["level"] += 1
        data[uid]["xp"] = 0
        await update.message.reply_text(
            f"🎉 {user.full_name} reached level {data[uid]['level']}!"
        )

    save_data(data)


async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.new_chat_members:
        return

    join_time = update.message.date.strftime("%H:%M")

    for member in update.message.new_chat_members:
        caption = (
            "🎩 STRICTLY CLUB\n\n"
            f"Welcome {member.full_name}\n"
            f"🕒 Joined at: {join_time}\n\n"
            "You’re in now.\n"
            "Start chatting, earn XP, and climb the ranks."
        )

        with open(WELCOME_IMAGE, "rb") as photo:
            await update.message.reply_photo(
                photo=photo,
                caption=caption,
            )


def main():
    if not TOKEN:
        raise ValueError("BOT_TOKEN is missing")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("rank", rank))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("wins", wins))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, give_xp))

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

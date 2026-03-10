import os
import json
import time
from pathlib import Path
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

XP_PER_MESSAGE = 15
FIRST_PLACE_XP = 200
SECOND_PLACE_XP = 100
THIRD_PLACE_XP = 50
RESET_SECONDS = 24 * 60 * 60


def load_data():
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    return {
        "users": {},
        "daily_cycle_started_at": time.time(),
        "announcement_chat_id": None
    }


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def xp_needed(level):
    return 100 + (level * 50)


def get_user_record(data, user):
    uid = str(user.id)

    if uid not in data["users"]:
        data["users"][uid] = {
            "name": user.full_name,
            "xp": 0,
            "level": 1,
            "daily_messages": 0,
            "wins": 0
        }
    else:
        data["users"][uid]["name"] = user.full_name

    return data["users"][uid]


def add_xp(record, amount):
    record["xp"] += amount
    leveled_up = False

    while record["xp"] >= xp_needed(record["level"]):
        record["xp"] -= xp_needed(record["level"])
        record["level"] += 1
        leveled_up = True

    return leveled_up


def get_top_three(data):
    users = list(data["users"].values())
    users = [u for u in users if u.get("daily_messages", 0) > 0]
    users.sort(key=lambda x: x["daily_messages"], reverse=True)
    return users[:3]


def format_time_left(seconds_left):
    hours = int(seconds_left // 3600)
    minutes = int((seconds_left % 3600) // 60)
    return f"{hours}h {minutes}m"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    await update.message.reply_text(
        "🎩 Strictly Club is live.\n"
        "Send messages to gain XP.\n"
        "Use /rank to check your level.\n"
        "Use /top to see today’s top posters."
    )


async def rank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user:
        return

    data = load_data()
    user = update.message.from_user
    record = get_user_record(data, user)
    save_data(data)

    await update.message.reply_text(
        f"👤 {record['name']}\n"
        f"⭐ Level: {record['level']}\n"
        f"🔥 XP: {record['xp']} / {xp_needed(record['level'])}\n"
        f"💬 Daily Messages: {record['daily_messages']}\n"
        f"🏆 Daily Wins: {record['wins']}"
    )


async def wins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user:
        return

    data = load_data()
    user = update.message.from_user
    record = get_user_record(data, user)
    save_data(data)

    await update.message.reply_text(
        f"🏆 {record['name']} has {record['wins']} daily top 3 wins."
    )


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    data = load_data()
    top_three = get_top_three(data)

    elapsed = time.time() - data.get("daily_cycle_started_at", time.time())
    seconds_left = max(0, RESET_SECONDS - elapsed)

    if not top_three:
        await update.message.reply_text(
            "🏆 STRICTLY CLUB DAILY LEADERBOARD\n\n"
            "No messages counted yet.\n"
            f"Reset in: {format_time_left(seconds_left)}"
        )
        return

    lines = ["🏆 STRICTLY CLUB DAILY LEADERBOARD", ""]
    medals = ["🥇", "🥈", "🥉"]

    for i, user in enumerate(top_three):
        lines.append(f"{medals[i]} {user['name']} — {user['daily_messages']} messages")

    lines.append("")
    lines.append(f"Reset in: {format_time_left(seconds_left)}")

    await update.message.reply_text("\n".join(lines))


async def give_xp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user:
        return

    if update.message.new_chat_members:
        return

    user = update.message.from_user
    data = load_data()

    record = get_user_record(data, user)
    record["daily_messages"] += 1

    if update.effective_chat:
        data["announcement_chat_id"] = update.effective_chat.id

    leveled_up = add_xp(record, XP_PER_MESSAGE)
    save_data(data)

    if leveled_up:
        await update.message.reply_text(
            f"🎉 {user.full_name} leveled up to Level {record['level']}!"
        )


async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.new_chat_members:
        return

    join_time = update.message.date.strftime("%H:%M")

    for user in update.message.new_chat_members:
        message = (
            "🎩 STRICTLY CLUB\n\n"
            f"Welcome {user.full_name}\n"
            f"🕒 Joined at: {join_time}\n\n"
            "You’re in now.\n"
            "Start chatting, earn XP, and climb the ranks."
        )

        with open(WELCOME_IMAGE, "rb") as photo:
            await update.message.reply_photo(
                photo=photo,
                caption=message
            )


async def announce_daily_winners(context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    chat_id = data.get("announcement_chat_id")
    top_three = get_top_three(data)

    if chat_id and top_three:
        rewards = [FIRST_PLACE_XP, SECOND_PLACE_XP, THIRD_PLACE_XP]
        medals = ["🥇", "🥈", "🥉"]
        titles = ["Top Poster", "Elite Poster", "Rising Poster"]

        lines = ["🏆 STRICTLY CLUB DAILY LEADERBOARD", ""]

        for i, user in enumerate(top_three):
            user["wins"] += 1
            add_xp(user, rewards[i])

            lines.append(
                f"{medals[i]} {user['name']} — {user['daily_messages']} messages\n"
                f"Title: {titles[i]}\n"
                f"Reward: +{rewards[i]} XP"
            )
            lines.append("")

        lines.append("New round starts now.")
        lines.append("Post to climb the ranks.")

        await context.bot.send_message(
            chat_id=chat_id,
            text="\n".join(lines)
        )

    for user in data["users"].values():
        user["daily_messages"] = 0

    data["daily_cycle_started_at"] = time.time()
    save_data(data)


def main():
    if not TOKEN:
        raise ValueError("BOT_TOKEN is missing.")

    app = Application.builder().token(TOKEN).build()

    data = load_data()
    if "daily_cycle_started_at" not in data:
        data["daily_cycle_started_at"] = time.time()
        save_data(data)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("rank", rank))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("wins", wins))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, give_xp))

    if app.job_queue is None:
        raise RuntimeError("JobQueue is not available. Install python-telegram-bot with job-queue support.")

    app.job_queue.run_repeating(
        announce_daily_winners,
        interval=RESET_SECONDS,
        first=RESET_SECONDS
    )

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

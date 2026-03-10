import os
import json
from pathlib import Path
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

TOKEN = os.getenv("BOT_TOKEN")
DATA_FILE = Path("xp_data.json")

def load_data():
    if DATA_FILE.exists():
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f)

def xp_needed(level):
    return 100 + (level * 50)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("XP system active! Send messages to gain XP.")

async def rank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    data = load_data()

    uid = str(user.id)
    if uid not in data:
        data[uid] = {"name": user.full_name, "xp": 0, "level": 1}

    save_data(data)

    xp = data[uid]["xp"]
    level = data[uid]["level"]

    await update.message.reply_text(
        f"👤 {user.full_name}\nLevel: {level}\nXP: {xp}"
    )

async def give_xp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    user = update.message.from_user
    data = load_data()

    uid = str(user.id)

    if uid not in data:
        data[uid] = {"name": user.full_name, "xp": 0, "level": 1}

    data[uid]["xp"] += 15

    if data[uid]["xp"] >= xp_needed(data[uid]["level"]):
        data[uid]["level"] += 1
        data[uid]["xp"] = 0
        await update.message.reply_text(
            f"🎉 {user.full_name} leveled up to {data[uid]['level']}!"
        )

    save_data(data)

def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("rank", rank))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, give_xp))

    app.run_polling()

if __name__ == "__main__":
    main()

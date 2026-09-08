import os
import threading
import asyncio
import httpx
from flask import Flask
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

from detector import is_outage_announcement, extract_areas, extract_date, extract_time_blocks
from database import (
    save_announcement,
    find_matching_users,
    record_notification,
    get_last_announcement_id,
    get_connection,
    get_todays_announcements,
)

load_dotenv()
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
SESSION_STRING = os.getenv("SESSION_STRING")

CHANNELS_TO_WATCH = ["eeuethiopia"]

KNOWN_AREAS = [
    "ዊንጌት", "wingate",
    "ቦሌ", "bole",
    "ፒያሳ", "piassa", "piazza",
    "መገናኛ", "megenagna",
    "ኮዬ", "koye",
    "አለምባንክ", "alembank",
    "ቤተል", "bethel",
]

waiting_for_location = set()

# ---------- Tiny web server (keeps Render awake) ----------
app_web = Flask(__name__)

@app_web.route("/")
def home():
    return "Power Alert Bot is running."

def run_web():
    app_web.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))


# ---------- Shared notification sender ----------
async def send_bot_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient() as http_client:
        await http_client.post(url, json={"chat_id": chat_id, "text": text})


async def check_todays_announcements_for_user(user_id, location):
    """When a user's location is newly confirmed, check if anything posted today already matches."""
    todays = get_todays_announcements()
    for announcement_id, raw_text, date_text, areas_text in todays:
        areas_list = areas_text.split("፣ ")
        matches = any(
            location.strip().lower() in area.lower() or area.lower() in location.strip().lower()
            for area in areas_list
        )
        if matches:
            newly_notified = record_notification(user_id, announcement_id)
            if newly_notified:
                time_blocks = extract_time_blocks(raw_text)
                matching_blocks = [
                    b for b in time_blocks
                    if any(
                        location.strip().lower() in a.lower() or a.lower() in location.strip().lower()
                        for a in b["areas"]
                    )
                ]
                time_info = "\n\n".join(
                    f"🕒 {b['time']}\nAreas: {', '.join(b['areas'])}" for b in matching_blocks
                )
                notification_text = (
                    f"⚡ Power Outage Notice for your area: {location}\n\n"
                    f"{date_text}\n\n"
                    f"{time_info}"
                )
                await send_bot_message(user_id, notification_text)


# ---------- Bot logic ----------
def find_matching_area(user_text: str):
    cleaned = user_text.strip().lower()
    for area in KNOWN_AREAS:
        if cleaned == area.lower() or cleaned in area.lower() or area.lower() in cleaned:
            return area
    return None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT location FROM users WHERE user_id = %s", (user_id,))
    row = cursor.fetchone()

    if row is None:
        cursor.execute(
            "INSERT INTO users (user_id, location, is_active) VALUES (%s, NULL, 1)",
            (user_id,),
        )
        conn.commit()
        waiting_for_location.add(user_id)
        await update.message.reply_text(
            "Welcome! I will notify you about power outages in your area.\n\n"
            "Please type the name of your area (English or Amharic), e.g. Ayat or አያት:"
        )
    else:
        cursor.execute("UPDATE users SET is_active = 1 WHERE user_id = %s", (user_id,))
        conn.commit()
        location = row[0] or "not set yet"
        await update.message.reply_text(
            f"Welcome back! Notifications are now ON.\nYour current area: {location}\n\n"
            "Use /setlocation to change it, or /stop to pause notifications."
        )
    cursor.close()
    conn.close()


async def setlocation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    waiting_for_location.add(user_id)
    await update.message.reply_text("Okay, please type your new area name:")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if user_id in waiting_for_location:
        matched_area = find_matching_area(text)
        conn = get_connection()
        cursor = conn.cursor()

        if matched_area:
            cursor.execute(
                "UPDATE users SET location = %s, location_status = 'confirmed' WHERE user_id = %s",
                (matched_area, user_id),
            )
            conn.commit()
            cursor.close()
            conn.close()
            waiting_for_location.remove(user_id)
            await update.message.reply_text(
                f"Got it! Your area is set to: {matched_area}\n\n"
                "You will be notified about power outages here. Use /stop to pause anytime."
            )
            await check_todays_announcements_for_user(user_id, matched_area)
        else:
            cursor.execute(
                "UPDATE users SET location = %s, location_status = 'pending' WHERE user_id = %s",
                (text, user_id),
            )
            conn.commit()
            cursor.close()
            conn.close()
            waiting_for_location.remove(user_id)

            await update.message.reply_text(
                f"Thanks! We couldn't automatically recognize \"{text}\" as a known area.\n"
                "It has been sent for review, and you'll be notified once it's confirmed."
            )
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    f"⚠️ Unrecognized location needs review:\n"
                    f"User ID: {user_id}\n"
                    f"Typed: \"{text}\"\n\n"
                    f"To confirm, reply with:\n"
                    f"/approve {user_id} <correct area name>"
                ),
            )
    else:
        await update.message.reply_text(
            "I didn't understand that. Use /setlocation to change your area, "
            "or /status to check your settings."
        )


async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    requester_id = update.effective_user.id
    if requester_id != ADMIN_ID:
        await update.message.reply_text("This command is for admin use only.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /approve <user_id> <correct area name>")
        return

    target_user_id = int(context.args[0])
    correct_area = " ".join(context.args[1:])

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET location = %s, location_status = 'confirmed' WHERE user_id = %s",
        (correct_area, target_user_id),
    )
    conn.commit()
    cursor.close()
    conn.close()

    await update.message.reply_text(f"Approved. User {target_user_id} area set to: {correct_area}")
    await context.bot.send_message(
        chat_id=target_user_id,
        text=f"Your area has been confirmed as: {correct_area}\nYou will now receive power outage alerts for this area.",
    )
    await check_todays_announcements_for_user(target_user_id, correct_area)


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_active = 0 WHERE user_id = %s", (user_id,))
    conn.commit()
    cursor.close()
    conn.close()
    await update.message.reply_text("Notifications paused. Send /start anytime to turn them back on.")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT location, is_active, location_status FROM users WHERE user_id = %s",
        (user_id,),
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if row is None:
        await update.message.reply_text("You haven't started yet. Send /start first.")
        return

    location, is_active, location_status = row
    location_text = location or "not set yet"
    status_text = "ON" if is_active == 1 else "PAUSED"
    pending_note = " (pending confirmation)" if location_status == "pending" else ""
    await update.message.reply_text(f"Area: {location_text}{pending_note}\nNotifications: {status_text}")


def run_bot():
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("setlocation", setlocation))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("approve", approve))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.run_polling(stop_signals=None)


# ---------- Listener logic ----------
def run_listener():
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

    @client.on(events.NewMessage(chats=CHANNELS_TO_WATCH))
    async def handle_new_message(event):
        text = event.raw_text or ""
        channel_name = event.chat.username if event.chat else "unknown"
        message_id = event.id

        if is_outage_announcement(text):
            date_text = extract_date(text)
            areas = extract_areas(text)
            time_blocks = extract_time_blocks(text)

            is_new = save_announcement(
                channel_name=channel_name,
                message_id=message_id,
                raw_text=text,
                date_text=date_text,
                areas_list=areas,
            )

            if is_new:
                announcement_id = get_last_announcement_id()
                matched_users = find_matching_users(areas)

                for user_id, location in matched_users:
                    newly_notified = record_notification(user_id, announcement_id)
                    if newly_notified:
                        matching_blocks = [
                            b for b in time_blocks
                            if any(
                                location.strip().lower() in a.lower() or a.lower() in location.strip().lower()
                                for a in b["areas"]
                            )
                        ]
                        time_info = "\n\n".join(
                            f"🕒 {b['time']}\nAreas: {', '.join(b['areas'])}" for b in matching_blocks
                        )
                        notification_text = (
                            f"⚡ Power Outage Notice for your area: {location}\n\n"
                            f"{date_text}\n\n"
                            f"{time_info}"
                        )
                        await send_bot_message(user_id, notification_text)

    with client:
        print("Listener is running.")
        client.run_until_disconnected()


if __name__ == "__main__":
    threading.Thread(target=run_web).start()
    threading.Thread(target=run_bot).start()
    run_listener()
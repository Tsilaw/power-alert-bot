import os
import html
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
    add_user_location,
    get_user_locations,
    delete_user_locations,
    update_user_location_status,
    learn_location,
    get_learned_match,
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
location_mode = {}  # user_id -> 'set' or 'add'

# ---------- Tiny web server (keeps Render awake) ----------
app_web = Flask(__name__)

@app_web.route("/")
def home():
    return "Power Alert Bot is running."

def run_web():
    app_web.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))


# ---------- Shared notification sender ----------
async def send_bot_message(chat_id, text, parse_mode=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    async with httpx.AsyncClient() as http_client:
        await http_client.post(url, json=payload)


def format_user_notification(location, date_text, matching_blocks, raw_areas_text, is_retroactive=False):
    esc_location = html.escape(location)
    esc_date = html.escape(date_text) if date_text else ""
    header = "⚡ <b>POWER OUTAGE NOTICE</b> ⚡" if not is_retroactive else "⚡ <b>EXISTING OUTAGE NOTICE FOR TODAY</b> ⚡"

    if matching_blocks:
        block_list = []
        for b in matching_blocks:
            t_str = html.escape(b['time'])
            areas_str = ", ".join(f"<b>{html.escape(a)}</b>" for a in b['areas'])
            block_list.append(f"⏰ <b>Time Schedule:</b> {t_str}\n📍 <b>Matching Areas:</b> {areas_str}")
        schedule_info = "\n\n".join(block_list)
    else:
        esc_areas = ", ".join(f"<b>{html.escape(a)}</b>" for a in raw_areas_text.split("፣ "))
        schedule_info = f"📍 <b>Affected Areas:</b> {esc_areas}"

    date_info = f"📅 <b>Date:</b> {esc_date}\n" if esc_date else ""

    text = (
        f"{header}\n\n"
        f"📍 <b>YOUR LOCATION:</b> <code>{esc_location}</code>\n"
        f"{date_info}"
        f"{schedule_info}\n\n"
        f"⚠️ <b>NOTICE:</b> There will be a power outage in your area, so please be ready!"
    )
    return text


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
            newly_notified = record_notification(user_id, announcement_id, location)
            if newly_notified:
                time_blocks = extract_time_blocks(raw_text)
                matching_blocks = [
                    b for b in time_blocks
                    if any(
                        location.strip().lower() in a.lower() or a.lower() in location.strip().lower()
                        for a in b["areas"]
                    )
                ]
                notification_text = format_user_notification(
                    location=location,
                    date_text=date_text,
                    matching_blocks=matching_blocks,
                    raw_areas_text=areas_text,
                    is_retroactive=True
                )
                await send_bot_message(user_id, notification_text, parse_mode="HTML")


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
    cursor.execute("SELECT is_active FROM users WHERE user_id = %s", (user_id,))
    row = cursor.fetchone()

    is_new_user = (row is None)

    if is_new_user:
        cursor.execute(
            "INSERT INTO users (user_id, location, is_active) VALUES (%s, NULL, 1)",
            (user_id,),
        )
        conn.commit()
    else:
        cursor.execute("UPDATE users SET is_active = 1 WHERE user_id = %s", (user_id,))
        conn.commit()
    cursor.close()
    conn.close()

    locs = get_user_locations(user_id)

    if not locs:
        waiting_for_location.add(user_id)
        location_mode[user_id] = "set"

        welcome_text = (
            "⚡ **Welcome to Ethiopia Power Alert Bot!** 🇪🇹\n\n"
            "💡 **What This Bot Does & How It Helps:**\n"
            "Unexpected power outages disrupt daily schedules, work, and business across Ethiopia. "
            "This bot automatically monitors official Ethiopian Electric Utility (@eeuethiopia) announcements "
            "24/7, extracts outage schedules, and instantly notifies you whenever power interruptions affect your area!\n\n"
            "🛠️ **Key Features:**\n"
            "• Real-time automated outage alerts for your saved area\n"
            "• Save multiple locations (Home, Work, Family area, etc.)\n"
            "• Check all today's outage announcements using `/todayalerts`\n\n"
            "👨‍💻 **Developer:** @MahammedAbdurahman\n"
            "📢 **Official Channel:** Please join @DesignDeploy for project updates & new bots!\n\n"
            "───────────────────\n"
            "📍 **Get Started:**\n"
            "Please type the name of your area (in English or Amharic), e.g. **Bole**, **Wingate**, or **ቦሌ**:"
        )
        await update.message.reply_text(welcome_text, parse_mode="Markdown")
    else:
        loc_str = "\n".join(f"• {loc} ({status})" for loc, status in locs)
        await update.message.reply_text(
            f"Welcome back! Notifications are ON.\n\n"
            f"📍 Your saved location(s):\n{loc_str}\n\n"
            "Commands:\n"
            "/addlocation - Add another location\n"
            "/setlocation - Reset location list\n"
            "/todayalerts - See today's outage announcements\n"
            "/status - Check your settings\n"
            "/stop - Pause notifications"
        )


async def setlocation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    waiting_for_location.add(user_id)
    location_mode[user_id] = "set"
    await update.message.reply_text(
        "Okay! Setting your location will replace your existing list.\n"
        "Please type your new area name:"
    )


async def addlocation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    waiting_for_location.add(user_id)
    location_mode[user_id] = "add"
    await update.message.reply_text(
        "Sure! Please type an additional area name you would like to receive alerts for:"
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if user_id in waiting_for_location:
        mode = location_mode.get(user_id, "set")

        # 1. Check direct match against KNOWN_AREAS
        matched_area = find_matching_area(text)

        # 2. If not found in KNOWN_AREAS, check learned_locations table
        if not matched_area:
            matched_area = get_learned_match(text)

        if mode == "set":
            delete_user_locations(user_id)

        if matched_area:
            add_user_location(user_id, matched_area, status="confirmed")
            waiting_for_location.remove(user_id)
            location_mode.pop(user_id, None)
            await update.message.reply_text(
                f"Got it! Saved area: {matched_area}\n\n"
                "You will be notified about power outages here. Use /addlocation to add more areas."
            )
            await check_todays_announcements_for_user(user_id, matched_area)
        else:
            add_user_location(user_id, text, status="pending")
            waiting_for_location.remove(user_id)
            location_mode.pop(user_id, None)

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
            "I didn't understand that. Use /setlocation or /addlocation to update your areas, "
            "or /todayalerts to see today's outage announcements."
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
    correct_area = " ".join(context.args[1:]).strip()

    locs = get_user_locations(target_user_id)
    pending_text = None
    for loc, status in locs:
        if status == "pending":
            pending_text = loc
            break

    if pending_text:
        # Learn the mapping so future users typing this exact text get auto-approved!
        learn_location(pending_text, correct_area)
        # Also delete the old pending location entry
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM user_locations WHERE user_id = %s AND location = %s",
            (target_user_id, pending_text),
        )
        conn.commit()
        cursor.close()
        conn.close()

    # Learn direct name as well
    learn_location(correct_area, correct_area)

    # Add confirmed location
    add_user_location(target_user_id, correct_area, status="confirmed")

    await update.message.reply_text(
        f"Approved! Saved mapping: '{pending_text or correct_area}' -> '{correct_area}'.\n"
        f"User {target_user_id} area set to: {correct_area}"
    )
    await context.bot.send_message(
        chat_id=target_user_id,
        text=f"Your area has been confirmed as: {correct_area}\nYou will now receive power outage alerts for this area.",
    )
    await check_todays_announcements_for_user(target_user_id, correct_area)


async def todayalerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    todays = get_todays_announcements()
    if not todays:
        await update.message.reply_text("No power outage announcements recorded today so far.")
        return

    messages = []
    for ann_id, raw_text, date_text, areas_text in todays:
        time_blocks = extract_time_blocks(raw_text)

        if time_blocks:
            blocks_formatted = []
            for b in time_blocks:
                time_str = html.escape(b['time'])
                areas_bullets = "\n".join(f"   • <b>{html.escape(a)}</b>" for a in b['areas']) if b['areas'] else "   • None specified"
                blocks_formatted.append(
                    f"⏰ <b>Time Schedule:</b> {time_str}\n"
                    f"📍 <b>Affected Locations:</b>\n{areas_bullets}"
                )
            schedule_details = "\n\n".join(blocks_formatted)
        else:
            areas_list = areas_text.split("፣ ")
            areas_bullets = "\n".join(f"   • <b>{html.escape(a)}</b>" for a in areas_list)
            schedule_details = f"📍 <b>Affected Locations:</b>\n{areas_bullets}"

        date_line = f"📅 <b>Date:</b> {html.escape(date_text)}\n" if date_text else ""

        messages.append(
            f"⚡ <b>Announcement #{ann_id}</b>\n"
            f"{date_line}"
            f"{schedule_details}"
        )

    full_response = "\n\n═══════════════════\n\n".join(messages)
    await update.message.reply_text(
        f"📢 <b>TODAY'S POWER OUTAGE ANNOUNCEMENTS</b> 🇪🇹\n\n{full_response}",
        parse_mode="HTML"
    )


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
    cursor.execute("SELECT is_active FROM users WHERE user_id = %s", (user_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if row is None:
        await update.message.reply_text("You haven't started yet. Send /start first.")
        return

    is_active = row[0]
    status_text = "ON" if is_active == 1 else "PAUSED"

    locs = get_user_locations(user_id)
    if not locs:
        loc_str = "No saved locations."
    else:
        loc_str = "\n".join(f"• {loc} ({status})" for loc, status in locs)

    await update.message.reply_text(
        f"📍 <b>Your Saved Location(s):</b>\n{loc_str}\n\n"
        f"Notifications: <b>{status_text}</b>\n\n"
        "Commands:\n"
        "/addlocation - Add another location\n"
        "/setlocation - Reset location list\n"
        "/todayalerts - See today's outage announcements\n"
        "/stop - Pause notifications",
        parse_mode="HTML"
    )


def run_bot():
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("setlocation", setlocation))
    application.add_handler(CommandHandler("addlocation", addlocation))
    application.add_handler(CommandHandler("todayalerts", todayalerts))
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
                    newly_notified = record_notification(user_id, announcement_id, location)
                    if newly_notified:
                        matching_blocks = [
                            b for b in time_blocks
                            if any(
                                location.strip().lower() in a.lower() or a.lower() in location.strip().lower()
                                for a in b["areas"]
                            )
                        ]
                        notification_text = format_user_notification(
                            location=location,
                            date_text=date_text,
                            matching_blocks=matching_blocks,
                            raw_areas_text=", ".join(areas),
                            is_retroactive=False
                        )
                        await send_bot_message(user_id, notification_text, parse_mode="HTML")

    with client:
        print("Listener is running.")
        client.run_until_disconnected()


if __name__ == "__main__":
    threading.Thread(target=run_web).start()
    threading.Thread(target=run_bot).start()
    run_listener()
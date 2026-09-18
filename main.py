import os
import html
import threading
import asyncio
import httpx
from flask import Flask
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telegram import Update, BotCommand, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

from detector import is_outage_announcement, extract_areas, extract_date, extract_time_blocks, is_area_match
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

# ---------- Helper keyboard & menu ----------
def get_main_keyboard():
    keyboard = [
        ["📍 My Status", "📢 Today's Alerts"],
        ["➕ Add Area", "🔄 Reset Area"],
        ["⏸️ Pause Alerts"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


async def post_init(application):
    commands = [
        BotCommand("status", "Check your saved locations & status"),
        BotCommand("todayalerts", "See today's power outage announcements"),
        BotCommand("addlocation", "Add an additional area (Home, Work, etc.)"),
        BotCommand("setlocation", "Reset and change your area list"),
        BotCommand("stop", "Pause outage notifications"),
        BotCommand("start", "Welcome message & bot details"),
    ]
    await application.bot.set_my_commands(commands)


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


def format_user_notification(location, date_text, matching_blocks, raw_areas_text, message_id=None, channel_name="eeuethiopia", is_retroactive=False):
    esc_location = html.escape(location)
    esc_date = html.escape(date_text) if date_text else ""
    header = "⚡ <b>POWER OUTAGE ALERT!</b> ⚡" if not is_retroactive else "⚡ <b>EXISTING OUTAGE NOTICE FOR TODAY</b> ⚡"

    if matching_blocks:
        block_list = []
        for b in matching_blocks:
            t_str = html.escape(b['time'])
            
            matched_areas = [a for a in b['areas'] if is_area_match(location, a)]
            other_areas = [a for a in b['areas'] if not is_area_match(location, a)]

            if matched_areas:
                matched_str = ", ".join(f"<b><u>{html.escape(m)}</u></b>" for m in matched_areas)
            else:
                matched_str = f"<b><u>{esc_location}</u></b>"

            if other_areas:
                other_str = "\n📍 <b>Other Affected Areas:</b> " + ", ".join(f"{html.escape(a)}" for a in other_areas)
            else:
                other_str = ""

            block_list.append(
                f"⏰ <b>Outage Time:</b> {t_str}\n"
                f"🎯 <b>Matched Location:</b> {matched_str}"
                f"{other_str}"
            )
        schedule_info = "\n\n".join(block_list)
    else:
        esc_areas = ", ".join(f"<b>{html.escape(a)}</b>" for a in raw_areas_text.split("፣ "))
        schedule_info = f"📍 <b>Affected Areas:</b> {esc_areas}"

    date_info = f"📅 <b>Date:</b> {esc_date}\n" if esc_date else ""

    c_name = channel_name or "eeuethiopia"
    if message_id:
        post_link = f"https://t.me/{c_name}/{message_id}"
        link_html = f"🔗 <a href=\"{post_link}\"><b>See Original Channel Post</b></a>\n\n"
    else:
        post_link = f"https://t.me/{c_name}"
        link_html = f"🔗 <a href=\"{post_link}\"><b>Visit EEU Official Channel</b></a>\n\n"

    text = (
        f"{header}\n\n"
        f"👤 <b>Your Saved Location:</b> <code>{esc_location}</code>\n"
        f"{date_info}"
        f"{schedule_info}\n\n"
        f"{link_html}"
        f"⚠️ <b>ATTENTION:</b> There will be a power outage in your area during the time listed above, so please be ready and charge your devices!"
    )
    return text


async def check_todays_announcements_for_user(user_id, location, todays=None):
    """When a user's location is newly confirmed, check if anything posted today already matches."""
    if todays is None:
        todays = get_todays_announcements()

    for announcement_id, raw_text, date_text, areas_text, channel_name, message_id in todays:
        areas_list = extract_areas(raw_text) if raw_text else areas_text.split("፣ ")
        matches = any(
            is_area_match(location, area)
            for area in areas_list
        )
        if matches:
            newly_notified = record_notification(user_id, announcement_id, location)
            if newly_notified:
                time_blocks = extract_time_blocks(raw_text)
                matching_blocks = [
                    b for b in time_blocks
                    if any(
                        is_area_match(location, a)
                        for a in b["areas"]
                    )
                ]
                notification_text = format_user_notification(
                    location=location,
                    date_text=date_text,
                    matching_blocks=matching_blocks,
                    raw_areas_text=areas_text,
                    message_id=message_id,
                    channel_name=channel_name or "eeuethiopia",
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
            "Use the quick menu buttons below or the [Menu] button anytime!",
            reply_markup=get_main_keyboard()
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
    user_obj = update.effective_user
    user_id = user_obj.id
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
                "You will be notified about power outages here. Tap buttons below or [Menu] anytime!",
                reply_markup=get_main_keyboard()
            )
            await check_todays_announcements_for_user(user_id, matched_area)
        else:
            add_user_location(user_id, text, status="pending")
            waiting_for_location.remove(user_id)
            location_mode.pop(user_id, None)

            await update.message.reply_text(
                f"Thanks! We couldn't automatically recognize \"{text}\" as a known area.\n"
                "It has been sent for review, and you'll be notified once it's confirmed.",
                reply_markup=get_main_keyboard()
            )

            full_name = html.escape(user_obj.full_name or "Unknown")
            username_str = f"@{user_obj.username}" if user_obj.username else "No @username"
            esc_text = html.escape(text)

            admin_alert = (
                f"⚠️ <b>Unrecognized location needs review:</b>\n\n"
                f"👤 <b>User:</b> {full_name} ({username_str})\n"
                f"🆔 <b>User ID:</b> <code>{user_id}</code>\n"
                f"📍 <b>Typed:</b> \"<code>{esc_text}</code>\"\n\n"
                f"To confirm, reply with:\n"
                f"<code>/approve {user_id} &lt;correct area name&gt;</code>"
            )

            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=admin_alert,
                parse_mode="HTML"
            )
    else:
        await update.message.reply_text(
            "Please use the menu buttons below or tap [Menu] to navigate!",
            reply_markup=get_main_keyboard()
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
        learn_location(pending_text, correct_area)
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM user_locations WHERE user_id = %s AND location = %s",
            (target_user_id, pending_text),
        )
        conn.commit()
        cursor.close()
        conn.close()

    learn_location(correct_area, correct_area)
    add_user_location(target_user_id, correct_area, status="confirmed")

    await update.message.reply_text(
        f"Approved! Saved mapping: '{pending_text or correct_area}' -> '{correct_area}'.\n"
        f"User {target_user_id} area set to: {correct_area}"
    )
    await context.bot.send_message(
        chat_id=target_user_id,
        text=f"Your area has been confirmed as: {correct_area}\nYou will now receive power outage alerts for this area.",
        reply_markup=get_main_keyboard()
    )
    await check_todays_announcements_for_user(target_user_id, correct_area)


async def todayalerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    todays = get_todays_announcements()
    if not todays:
        await update.message.reply_text("No power outage announcements recorded today so far.", reply_markup=get_main_keyboard())
        return

    messages = []
    for ann_id, raw_text, date_text, areas_text, channel_name, message_id in todays:
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
        
        c_name = channel_name or "eeuethiopia"
        if message_id:
            link_str = f"\n\n🔗 <a href=\"https://t.me/{c_name}/{message_id}\"><b>See Original Channel Post</b></a>"
        else:
            link_str = f"\n\n🔗 <a href=\"https://t.me/{c_name}\"><b>Visit EEU Official Channel</b></a>"

        messages.append(
            f"⚡ <b>Announcement #{ann_id}</b>\n"
            f"{date_line}"
            f"{schedule_details}"
            f"{link_str}"
        )

    full_response = "\n\n═══════════════════\n\n".join(messages)
    await update.message.reply_text(
        f"📢 <b>TODAY'S POWER OUTAGE ANNOUNCEMENTS</b> 🇪🇹\n\n{full_response}",
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_active = 0 WHERE user_id = %s", (user_id,))
    conn.commit()
    cursor.close()
    conn.close()
    await update.message.reply_text("Notifications paused. Send /start anytime to turn them back on.", reply_markup=get_main_keyboard())


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
        loc_str = "\n".join(f"• <b>{html.escape(loc)}</b> ({html.escape(loc_status)})" for loc, loc_status in locs)

    await update.message.reply_text(
        f"📍 <b>Your Saved Location(s):</b>\n{loc_str}\n\n"
        f"Notifications: <b>{html.escape(status_text)}</b>",
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )


def run_bot():
    application = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("setlocation", setlocation))
    application.add_handler(CommandHandler("addlocation", addlocation))
    application.add_handler(CommandHandler("todayalerts", todayalerts))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("approve", approve))

    # Button text handlers
    application.add_handler(MessageHandler(filters.Regex("^📍 My Status$"), status))
    application.add_handler(MessageHandler(filters.Regex("^📢 Today's Alerts$"), todayalerts))
    application.add_handler(MessageHandler(filters.Regex("^➕ Add Area$"), addlocation))
    application.add_handler(MessageHandler(filters.Regex("^🔄 Reset Area$"), setlocation))
    application.add_handler(MessageHandler(filters.Regex("^⏸️ Pause Alerts$"), stop))

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
                                is_area_match(location, a)
                                for a in b["areas"]
                            )
                        ]
                        notification_text = format_user_notification(
                            location=location,
                            date_text=date_text,
                            matching_blocks=matching_blocks,
                            raw_areas_text=", ".join(areas),
                            message_id=message_id,
                            channel_name=channel_name or "eeuethiopia",
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
import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from database import get_connection

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

waiting_for_location = set()

KNOWN_AREAS = [
    "ዊንጌት", "wingate",
    "ቦሌ", "bole",
    "ፒያሳ", "piassa", "piazza",
    "መገናኛ", "megenagna",
    "ኮዬ", "koye",
    "አለምባንክ", "alembank",
    "ቤተል", "bethel",
]


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
    cursor.execute("SELECT location FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()

    if row is None:
        cursor.execute(
            "INSERT INTO users (user_id, location, is_active) VALUES (?, NULL, 1)",
            (user_id,),
        )
        conn.commit()
        waiting_for_location.add(user_id)
        await update.message.reply_text(
            "Welcome! I will notify you about power outages in your area.\n\n"
            "Please type the name of your area (English or Amharic), e.g. Ayat or አያት:"
        )
    else:
        cursor.execute(
            "UPDATE users SET is_active = 1 WHERE user_id = ?", (user_id,)
        )
        conn.commit()
        location = row[0] or "not set yet"
        await update.message.reply_text(
            f"Welcome back! Notifications are now ON.\nYour current area: {location}\n\n"
            "Use /setlocation to change it, or /stop to pause notifications."
        )

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
                "UPDATE users SET location = ?, location_status = 'confirmed' WHERE user_id = ?",
                (matched_area, user_id),
            )
            conn.commit()
            conn.close()
            waiting_for_location.remove(user_id)
            await update.message.reply_text(
                f"Got it! Your area is set to: {matched_area}\n\n"
                "You will be notified about power outages here. Use /stop to pause anytime."
            )
        else:
            cursor.execute(
                "UPDATE users SET location = ?, location_status = 'pending' WHERE user_id = ?",
                (text, user_id),
            )
            conn.commit()
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
        await update.message.reply_text(
            "Usage: /approve <user_id> <correct area name>"
        )
        return

    target_user_id = int(context.args[0])
    correct_area = " ".join(context.args[1:])

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET location = ?, location_status = 'confirmed' WHERE user_id = ?",
        (correct_area, target_user_id),
    )
    conn.commit()
    conn.close()

    await update.message.reply_text(f"Approved. User {target_user_id} area set to: {correct_area}")

    await context.bot.send_message(
        chat_id=target_user_id,
        text=f"Your area has been confirmed as: {correct_area}\nYou will now receive power outage alerts for this area.",
    )


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_active = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    await update.message.reply_text(
        "Notifications paused. Send /start anytime to turn them back on."
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT location, is_active, location_status FROM users WHERE user_id = ?",
        (user_id,),
    )
    row = cursor.fetchone()
    conn.close()

    if row is None:
        await update.message.reply_text("You haven't started yet. Send /start first.")
        return

    location, is_active, location_status = row
    location_text = location or "not set yet"
    status_text = "ON" if is_active == 1 else "PAUSED"
    pending_note = " (pending confirmation)" if location_status == "pending" else ""
    await update.message.reply_text(
        f"Area: {location_text}{pending_note}\nNotifications: {status_text}"
    )


if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setlocation", setlocation))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("Bot is running... Press Ctrl+C to stop.")
    app.run_polling()
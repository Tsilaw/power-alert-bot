import os
import asyncio
import httpx
from dotenv import load_dotenv
from telethon import TelegramClient, events
from detector import is_outage_announcement, extract_areas, extract_date, extract_time_blocks
from database import save_announcement, find_matching_users, record_notification, get_last_announcement_id

load_dotenv()
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

CHANNELS_TO_WATCH = [
    "eeuethiopia",
]

from telethon.sessions import StringSession

SESSION_STRING = os.getenv("SESSION_STRING")
client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)


async def send_bot_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient() as http_client:
        await http_client.post(url, json={"chat_id": chat_id, "text": text})


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

        with open("listener_log.txt", "a", encoding="utf-8") as f:
            f.write("=" * 50 + "\n")
            f.write(f"Outage announcement detected (new: {is_new})\n")
            f.write(f"Channel: {channel_name}, Message ID: {message_id}\n")
            f.write(f"Date: {date_text}\n")
            f.write("Areas:\n")
            for area in areas:
                f.write(f"- {area}\n")
            f.write("=" * 50 + "\n\n")

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

            with open("listener_log.txt", "a", encoding="utf-8") as f:
                f.write(f"Notified {len(matched_users)} matching user(s) for announcement ID {announcement_id}\n\n")
    else:
        with open("listener_log.txt", "a", encoding="utf-8") as f:
            f.write(f"Message received but NOT an outage announcement (Message ID: {message_id})\n\n")


async def main():
    print("Listener is running. Waiting for new messages...")
    print("Watching channels:", CHANNELS_TO_WATCH)
    await client.run_until_disconnected()


if __name__ == "__main__":
    with client:
        client.loop.run_until_complete(main())
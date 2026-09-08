import os
import asyncio
from dotenv import load_dotenv
from telethon import TelegramClient
from detector import is_outage_announcement, extract_areas, extract_date
from database import save_announcement

load_dotenv()
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")

CHANNEL_USERNAME = "eeuethiopia"

client = TelegramClient("power_alert_session", API_ID, API_HASH)


async def main():
    async with client:
        with open("backfill_log.txt", "w", encoding="utf-8") as f:
            f.write("Checking the last 20 messages...\n\n")
            async for message in client.iter_messages(CHANNEL_USERNAME, limit=20):
                text = message.text or ""
                if is_outage_announcement(text):
                    date_text = extract_date(text)
                    areas = extract_areas(text)
                    is_new = save_announcement(
                        channel_name=CHANNEL_USERNAME,
                        message_id=message.id,
                        raw_text=text,
                        date_text=date_text,
                        areas_list=areas,
                    )
                    f.write("=" * 50 + "\n")
                    f.write(f"Message ID: {message.id} | New: {is_new}\n")
                    f.write(f"Date: {date_text}\n")
                    f.write("Areas:\n")
                    for area in areas:
                        f.write(f"- {area}\n")
                    f.write("=" * 50 + "\n\n")

        print("Done! Check backfill_log.txt for results.")


if __name__ == "__main__":
    asyncio.run(main())
import os
import asyncio
from dotenv import load_dotenv
from telethon import TelegramClient

load_dotenv()
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")

CHANNEL_USERNAME = "eeuethiopia"

client = TelegramClient("power_alert_session", API_ID, API_HASH)


async def main():
    async with client:
        print(f"Fetching the last 5 messages from {CHANNEL_USERNAME}...")
        with open("recent_messages.txt", "w", encoding="utf-8") as f:
            async for message in client.iter_messages(CHANNEL_USERNAME, limit=5):
                f.write("=" * 50 + "\n")
                f.write(f"Date: {message.date}\n")
                f.write("Text:\n")
                f.write((message.text or "") + "\n")
                f.write("=" * 50 + "\n\n")
        print("Done! Open recent_messages.txt to see the results.")


if __name__ == "__main__":
    asyncio.run(main())
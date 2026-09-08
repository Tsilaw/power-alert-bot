import os
import asyncio
import httpx
from dotenv import load_dotenv
from detector import is_outage_announcement, extract_areas, extract_date, extract_time_blocks
from database import save_announcement, find_matching_users, record_notification, get_last_announcement_id

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# A fake but realistic new announcement, with a made-up unique message ID
FAKE_MESSAGE_ID = 999001
FAKE_CHANNEL = "eeuethiopia"

FAKE_TEXT = """የጥገና ሥራ ለማከናወን የሚቋረጥ የኃይል አቅርቦት 

ዛሬ ጳጉሜ 4 ቀን 2018 ዓ.ም የጥገና ሥራ ለማከናወን የኃይል አቅርቦት የሚቋረጥባቸው አካባቢዎች ፡-

✅ከጠዋቱ 3፡00-8፡00

👉ጃንሜዳ ፣ ስድስት ኪሎ ፣ ፒያሳ እና አካባቢው

ስለሆነም በአካባቢው የምትገኙ ክቡራን ደንበኞቻችን ይህንኑ በመገንዘብ አስፈላጊውን ቅድመ ዝግጅት እንድታደርጉ በአክብሮት እናሳውቃለን፡፡

#የኢትዮጵያኤሌክትሪክአገልግሎት"""


async def send_bot_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient() as http_client:
        await http_client.post(url, json={"chat_id": chat_id, "text": text})


async def main():
    with open("simulate_log.txt", "w", encoding="utf-8") as f:
        f.write("Simulating a new incoming message...\n\n")

        if is_outage_announcement(FAKE_TEXT):
            date_text = extract_date(FAKE_TEXT)
            areas = extract_areas(FAKE_TEXT)
            time_blocks = extract_time_blocks(FAKE_TEXT)

            is_new = save_announcement(
                channel_name=FAKE_CHANNEL,
                message_id=FAKE_MESSAGE_ID,
                raw_text=FAKE_TEXT,
                date_text=date_text,
                areas_list=areas,
            )

            f.write(f"Is outage announcement: True\n")
            f.write(f"Saved as new: {is_new}\n")
            f.write(f"Date: {date_text}\n")
            f.write(f"Areas: {areas}\n\n")

            if is_new:
                announcement_id = get_last_announcement_id()
                matched_users = find_matching_users(areas)
                f.write(f"Matched users: {len(matched_users)}\n\n")

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
                        f.write(f"Notified user {user_id}\n")
        else:
            f.write("Not detected as an outage announcement.\n")

    print("Done! Check simulate_log.txt and your Telegram.")


if __name__ == "__main__":
    asyncio.run(main())
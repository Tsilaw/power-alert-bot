import os
import asyncio
import httpx
from dotenv import load_dotenv
from database import get_connection, find_matching_users, record_notification
from detector import extract_time_blocks

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

ANNOUNCEMENT_ID_TO_TEST = 1


async def send_bot_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient() as http_client:
        response = await http_client.post(url, json={"chat_id": chat_id, "text": text})
        return response.json()


async def main():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT date_text, areas, raw_text FROM announcements WHERE id = ?",
        (ANNOUNCEMENT_ID_TO_TEST,),
    )
    row = cursor.fetchone()
    conn.close()

    if row is None:
        print("Announcement not found.")
        return

    date_text, areas_text, raw_text = row
    areas_list = areas_text.split("፣ ")
    time_blocks = extract_time_blocks(raw_text)

    matched_users = find_matching_users(areas_list)

    with open("test_notify_log.txt", "w", encoding="utf-8") as f:
        f.write(f"Matched users: {len(matched_users)}\n\n")
        for user_id, location in matched_users:
            f.write(f"User {user_id} matched on location: {location}\n")

    for user_id, location in matched_users:
        newly_notified = record_notification(user_id, ANNOUNCEMENT_ID_TO_TEST)
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

            result = await send_bot_message(user_id, notification_text)
            with open("test_notify_log.txt", "a", encoding="utf-8") as f:
                f.write(f"\nSend result for user {user_id}: {result}\n")
        else:
            with open("test_notify_log.txt", "a", encoding="utf-8") as f:
                f.write(f"\nUser {user_id} was already notified before, skipped.\n")

    print("Done! Check test_notify_log.txt")


if __name__ == "__main__":
    asyncio.run(main())
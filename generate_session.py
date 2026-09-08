import os
from dotenv import load_dotenv
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

load_dotenv()
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")

with TelegramClient(StringSession(), API_ID, API_HASH) as client:
    session_string = client.session.save()
    with open("session_string.txt", "w", encoding="utf-8") as f:
        f.write(session_string)
    print("Session string saved to session_string.txt")
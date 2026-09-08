import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")


def get_connection():
    """Opens a connection to our Postgres database."""
    return psycopg2.connect(DATABASE_URL)


def create_tables():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            location TEXT,
            is_active INTEGER DEFAULT 1,
            location_status TEXT DEFAULT 'confirmed',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS announcements (
            id SERIAL PRIMARY KEY,
            channel_name TEXT,
            message_id BIGINT,
            raw_text TEXT,
            date_text TEXT,
            time_text TEXT,
            reason_text TEXT,
            areas TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(channel_name, message_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sent_notifications (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            announcement_id INTEGER,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, announcement_id)
        )
    """)

    conn.commit()
    cursor.close()
    conn.close()
    print("Database tables created successfully.")


def save_announcement(channel_name, message_id, raw_text, date_text, areas_list):
    conn = get_connection()
    cursor = conn.cursor()
    areas_text = "፣ ".join(areas_list)

    try:
        cursor.execute("""
            INSERT INTO announcements (channel_name, message_id, raw_text, date_text, areas)
            VALUES (%s, %s, %s, %s, %s)
        """, (channel_name, message_id, raw_text, date_text, areas_text))
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        cursor.close()
        conn.close()
        return False


def find_matching_users(areas_list):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT user_id, location FROM users
        WHERE is_active = 1 AND location_status = 'confirmed' AND location IS NOT NULL
    """)
    all_users = cursor.fetchall()
    cursor.close()
    conn.close()

    matched = []
    for user_id, location in all_users:
        for area in areas_list:
            if location.strip().lower() in area.lower() or area.lower() in location.strip().lower():
                matched.append((user_id, location))
                break

    return matched


def record_notification(user_id, announcement_id):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO sent_notifications (user_id, announcement_id)
            VALUES (%s, %s)
        """, (user_id, announcement_id))
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        cursor.close()
        conn.close()
        return False


def get_last_announcement_id():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM announcements ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row[0] if row else None


if __name__ == "__main__":
    create_tables()
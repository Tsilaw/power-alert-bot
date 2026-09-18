import os
import psycopg2
from dotenv import load_dotenv
from detector import is_area_match

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")


def get_connection():
    """Opens a connection to our Postgres database."""
    return psycopg2.connect(DATABASE_URL)


def create_tables():
    conn = get_connection()
    cursor = conn.cursor()

    # Core users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            location TEXT,
            is_active INTEGER DEFAULT 1,
            location_status TEXT DEFAULT 'confirmed',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Multi-location support
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_locations (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            location TEXT,
            status TEXT DEFAULT 'confirmed',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, location)
        )
    """)

    # Auto-learning for admin approvals
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS learned_locations (
            id SERIAL PRIMARY KEY,
            typed_text TEXT UNIQUE,
            approved_area TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Announcements table
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

    # Sent notifications table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sent_notifications (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            announcement_id INTEGER,
            location TEXT,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Migrations & index adjustments for existing database instances
    cursor.execute("""
        ALTER TABLE sent_notifications ADD COLUMN IF NOT EXISTS location TEXT;
    """)

    # Drop old 2-column constraint if present and add 3-column unique constraint
    try:
        cursor.execute("ALTER TABLE sent_notifications DROP CONSTRAINT IF EXISTS sent_notifications_user_id_announcement_id_key;")
        cursor.execute("ALTER TABLE sent_notifications DROP CONSTRAINT IF EXISTS sent_notifications_user_announcement_loc_key;")
        cursor.execute("ALTER TABLE sent_notifications ADD CONSTRAINT sent_notifications_user_announcement_loc_key UNIQUE (user_id, announcement_id, location);")
    except Exception as e:
        conn.rollback()
        conn = get_connection()
        cursor = conn.cursor()

    # Migrate existing single user locations into user_locations table
    cursor.execute("""
        INSERT INTO user_locations (user_id, location, status)
        SELECT user_id, location, location_status FROM users
        WHERE location IS NOT NULL AND location != ''
        ON CONFLICT (user_id, location) DO NOTHING;
    """)

    conn.commit()
    cursor.close()
    conn.close()
    print("Database tables created and updated successfully.")


def add_user_location(user_id, location, status="confirmed"):
    """Adds or updates a location for a user."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO user_locations (user_id, location, status)
        VALUES (%s, %s, %s)
        ON CONFLICT (user_id, location) DO UPDATE SET status = EXCLUDED.status
    """, (user_id, location, status))

    # Keep single location column updated for backwards compatibility
    cursor.execute("""
        UPDATE users SET location = %s, location_status = %s, is_active = 1
        WHERE user_id = %s
    """, (location, status, user_id))

    conn.commit()
    cursor.close()
    conn.close()


def get_user_locations(user_id):
    """Returns a list of (location, status) tuples for a user."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT location, status FROM user_locations
        WHERE user_id = %s ORDER BY id ASC
    """, (user_id,))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def delete_user_locations(user_id):
    """Clears all saved locations for a user."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM user_locations WHERE user_id = %s", (user_id,))
    cursor.execute("UPDATE users SET location = NULL WHERE user_id = %s", (user_id,))
    conn.commit()
    cursor.close()
    conn.close()


def update_user_location_status(user_id, location, status):
    """Updates the status of a specific location for a user."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE user_locations SET status = %s
        WHERE user_id = %s AND location = %s
    """, (status, user_id, location))
    cursor.execute("""
        UPDATE users SET location_status = %s
        WHERE user_id = %s AND location = %s
    """, (status, user_id, location))
    conn.commit()
    cursor.close()
    conn.close()


def learn_location(typed_text, approved_area):
    """Saves a mapping from user typed text to an admin-approved area name."""
    conn = get_connection()
    cursor = conn.cursor()
    key = typed_text.strip().lower()
    cursor.execute("""
        INSERT INTO learned_locations (typed_text, approved_area)
        VALUES (%s, %s)
        ON CONFLICT (typed_text) DO UPDATE SET approved_area = EXCLUDED.approved_area
    """, (key, approved_area))
    conn.commit()
    cursor.close()
    conn.close()


def get_learned_match(typed_text):
    """Returns approved area name if typed_text was previously learned, else None."""
    conn = get_connection()
    cursor = conn.cursor()
    key = typed_text.strip().lower()
    cursor.execute("""
        SELECT approved_area FROM learned_locations
        WHERE typed_text = %s
    """, (key,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row[0] if row else None


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
    """Finds active users whose confirmed locations match any area in areas_list."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT ul.user_id, ul.location
        FROM user_locations ul
        JOIN users u ON ul.user_id = u.user_id
        WHERE u.is_active = 1 AND ul.status = 'confirmed' AND ul.location IS NOT NULL
    """)
    all_user_locs = cursor.fetchall()
    cursor.close()
    conn.close()

    matched = []
    for user_id, location in all_user_locs:
        for area in areas_list:
            if is_area_match(location, area):
                matched.append((user_id, location))
                break

    return matched


def record_notification(user_id, announcement_id, location):
    """Records that a notification was sent for a user, announcement, and specific location."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO sent_notifications (user_id, announcement_id, location)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, announcement_id, location) DO NOTHING
        """, (user_id, announcement_id, location))
        inserted = (cursor.rowcount > 0)
        conn.commit()
        cursor.close()
        conn.close()
        return inserted
    except Exception:
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


def get_todays_announcements():
    """Returns all announcements saved today (based on when we processed them or within 24h), including channel_name and message_id."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, raw_text, date_text, areas, channel_name, message_id FROM announcements
        WHERE created_at >= NOW() - INTERVAL '24 hours' OR created_at::date = CURRENT_DATE
        ORDER BY id DESC
    """)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


if __name__ == "__main__":
    create_tables()
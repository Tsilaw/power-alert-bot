from database import get_connection

conn = get_connection()
cursor = conn.cursor()
cursor.execute("SELECT id, channel_name, message_id, date_text, areas FROM announcements")
rows = cursor.fetchall()
conn.close()

with open("db_check_output.txt", "w", encoding="utf-8") as f:
    f.write(f"Total announcements saved: {len(rows)}\n\n")
    for row in rows:
        f.write("=" * 50 + "\n")
        f.write(f"ID: {row[0]}\n")
        f.write(f"Channel: {row[1]}\n")
        f.write(f"Message ID: {row[2]}\n")
        f.write(f"Date: {row[3]}\n")
        f.write(f"Areas: {row[4]}\n")
        f.write("=" * 50 + "\n\n")

print("Done! Check db_check_output.txt")
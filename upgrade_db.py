from database import get_connection

conn = get_connection()
cursor = conn.cursor()

cursor.execute("""
    ALTER TABLE users ADD COLUMN location_status TEXT DEFAULT 'confirmed'
""")

conn.commit()
conn.close()
print("Database upgraded: location_status column added.")
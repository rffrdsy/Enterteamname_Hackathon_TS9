import sqlite3
import random

db_path = r"C:\Users\putra\Desktop\mooOSFE\Enterteamname_Hackathon_TS9\telebot\backend\mooos.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Get all cows
cursor.execute("SELECT id, barn, caretaker FROM cows")
rows = cursor.fetchall()

for row_id, barn, caretaker in rows:
    new_barn = barn
    new_caretaker = caretaker
    
    # If barn/caretaker is missing, assign a default
    if not barn or not caretaker:
        new_caretaker = random.choice(["ABYASA", "AXEL"])
        new_barn = "A" if new_caretaker == "ABYASA" else "B"
        
    cursor.execute(
        """
        UPDATE cows 
        SET status = 'AVAILABLE', barn = ?, caretaker = ? 
        WHERE id = ?
        """,
        (new_barn, new_caretaker, row_id)
    )

conn.commit()
conn.close()
print("All cows have been updated to AVAILABLE and assigned to caretakers/barns where missing.")

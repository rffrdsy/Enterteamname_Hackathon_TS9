from database import conn, cursor
cursor.execute("SELECT id, name, barn, role FROM members WHERE role = 'Penanggungjawab Ternak'")
print("Penanggungjawab:", cursor.fetchall())

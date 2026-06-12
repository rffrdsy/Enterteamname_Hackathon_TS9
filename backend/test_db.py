import sqlite3
conn = sqlite3.connect('mooos.db')
cursor = conn.cursor()
cursor.execute('SELECT cow_code, barn, status FROM cows')
print(cursor.fetchall()[:20])
conn.close()

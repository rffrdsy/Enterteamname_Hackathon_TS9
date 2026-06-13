import sqlite3
import os

db_path = "mooos.db"
print("DB Exists:", os.path.exists(db_path))

conn = sqlite3.connect(db_path)
cur = conn.cursor()

try:
    # Get columns of feed_financials
    cur.execute("PRAGMA table_info(feed_financials)")
    print("feed_financials columns:", cur.fetchall())
    
    # Get row count of feed_financials
    cur.execute("SELECT COUNT(*) FROM feed_financials")
    print("feed_financials count:", cur.fetchone()[0])

    # Get rows of feed_financials
    cur.execute("SELECT * FROM feed_financials LIMIT 3")
    print("feed_financials samples:", cur.fetchall())

    # Get members role and count
    cur.execute("SELECT role, COUNT(*) FROM members GROUP BY role")
    print("Members count by role:", cur.fetchall())

    # Get cows count and status
    cur.execute("SELECT status, COUNT(*) FROM cows GROUP BY status")
    print("Cows count by status:", cur.fetchall())
    
    # Run the get_aggregate_report calculation
    cur.execute("SELECT SUM(estimated_revenue) FROM milk_financials")
    print("SUM(milk estimated_revenue):", cur.fetchone()[0])
    
    cur.execute("SELECT SUM(estimated_revenue) FROM waste_financials")
    print("SUM(waste estimated_revenue):", cur.fetchone()[0])
    
except Exception as e:
    print("Error:", e)
finally:
    conn.close()

import sqlite3

conn = sqlite3.connect(
    "mooos.db",
    check_same_thread=False
)

cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS cows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cow_code TEXT UNIQUE,
    owner_id INTEGER,
    weight REAL,
    status TEXT,
    caretaker TEXT,
    feed_qty_needed REAL DEFAULT 0,

    FOREIGN KEY(owner_id)
    REFERENCES members(id)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS feed_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    po_code TEXT,
    qty REAL,
    price_per_kg REAL DEFAULT 5000,
    status TEXT,
    supplier TEXT
)
""")

# Tabel untuk mencatat supplier mana saja yang menerima notifikasi PO
cursor.execute("""
CREATE TABLE IF NOT EXISTS feed_order_recipients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    po_code TEXT,
    telegram_id INTEGER
)
""")

# Jalankan migrasi kolom jika tabel sudah ada sebelumnya
cursor.execute("PRAGMA table_info(cows)")
cows_cols = [row[1] for row in cursor.fetchall()]
if "feed_qty_needed" not in cows_cols:
    cursor.execute("ALTER TABLE cows ADD COLUMN feed_qty_needed REAL DEFAULT 0")

cursor.execute("PRAGMA table_info(feed_orders)")
fo_cols = [row[1] for row in cursor.fetchall()]
if "price_per_kg" not in fo_cols:
    cursor.execute("ALTER TABLE feed_orders ADD COLUMN price_per_kg REAL DEFAULT 5000")
if "supplier" not in fo_cols:
    cursor.execute("ALTER TABLE feed_orders ADD COLUMN supplier TEXT")

conn.commit()
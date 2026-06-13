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
    nik TEXT,
    phone TEXT,
    alamat TEXT,
    role TEXT DEFAULT 'Penitip Ternak'
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
    barn TEXT,
    hash_id TEXT,

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

# Tabel untuk menyimpan referensi pesan agar tombol bisa dihapus setelah di-approve
cursor.execute("""
CREATE TABLE IF NOT EXISTS message_refs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ref_type TEXT,
    ref_id TEXT,
    chat_id INTEGER,
    message_id INTEGER
)
""")


# Jalankan migrasi kolom jika tabel sudah ada sebelumnya
cursor.execute("PRAGMA table_info(cows)")
cows_cols = [row[1] for row in cursor.fetchall()]
if "feed_qty_needed" not in cows_cols:
    cursor.execute("ALTER TABLE cows ADD COLUMN feed_qty_needed REAL DEFAULT 0")
if "barn" not in cows_cols:
    cursor.execute("ALTER TABLE cows ADD COLUMN barn TEXT")
if "hash_id" not in cows_cols:
    cursor.execute("ALTER TABLE cows ADD COLUMN hash_id TEXT")

# Migrasi kolom SPK (surat penjualan)
if "jenis" not in cows_cols:
    cursor.execute("ALTER TABLE cows ADD COLUMN jenis TEXT")
if "umur" not in cows_cols:
    cursor.execute("ALTER TABLE cows ADD COLUMN umur TEXT")
if "tgl_masuk" not in cows_cols:
    cursor.execute("ALTER TABLE cows ADD COLUMN tgl_masuk TEXT")
if "deskripsi" not in cows_cols:
    cursor.execute("ALTER TABLE cows ADD COLUMN deskripsi TEXT")
if "foto_path" not in cows_cols:
    cursor.execute("ALTER TABLE cows ADD COLUMN foto_path TEXT")
if "lactate_status" not in cows_cols:
    cursor.execute("ALTER TABLE cows ADD COLUMN lactate_status TEXT DEFAULT 'Kering'")
if "litre_milked_today" not in cows_cols:
    cursor.execute("ALTER TABLE cows ADD COLUMN litre_milked_today REAL DEFAULT 0.0")

cursor.execute("PRAGMA table_info(feed_orders)")
fo_cols = [row[1] for row in cursor.fetchall()]
if "price_per_kg" not in fo_cols:
    cursor.execute("ALTER TABLE feed_orders ADD COLUMN price_per_kg REAL DEFAULT 5000")
if "supplier" not in fo_cols:
    cursor.execute("ALTER TABLE feed_orders ADD COLUMN supplier TEXT")

# Migrasi kolom members jika tabel sudah ada sebelumnya
cursor.execute("PRAGMA table_info(members)")
members_cols = [row[1] for row in cursor.fetchall()]
if "nik" not in members_cols:
    cursor.execute("ALTER TABLE members ADD COLUMN nik TEXT")
if "alamat" not in members_cols:
    cursor.execute("ALTER TABLE members ADD COLUMN alamat TEXT")
if "role" not in members_cols:
    cursor.execute("ALTER TABLE members ADD COLUMN role TEXT DEFAULT 'Penitip Ternak'")
if "barn" not in members_cols:
    cursor.execute("ALTER TABLE members ADD COLUMN barn TEXT")
if "iuran_wajib" not in members_cols:
    cursor.execute("ALTER TABLE members ADD COLUMN iuran_wajib REAL DEFAULT 50000.0")
if "iuran_pokok" not in members_cols:
    cursor.execute("ALTER TABLE members ADD COLUMN iuran_pokok REAL DEFAULT 100000.0")
    # Seed barn assignment: Penanggungjawab pertama → A, kedua → B
    cursor.execute("""
        UPDATE members SET barn = 'A'
        WHERE role = 'Penanggungjawab Ternak'
        AND id = (
            SELECT id FROM members WHERE role = 'Penanggungjawab Ternak'
            ORDER BY id ASC LIMIT 1
        )
    """)
    cursor.execute("""
        UPDATE members SET barn = 'B'
        WHERE role = 'Penanggungjawab Ternak'
        AND id = (
            SELECT id FROM members WHERE role = 'Penanggungjawab Ternak'
            ORDER BY id ASC LIMIT 1 OFFSET 1
        )
    """)
cursor.execute("""
CREATE TABLE IF NOT EXISTS feed_financials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT UNIQUE,
    total_kg REAL,
    price_per_kg REAL,
    estimated_cost REAL
)
""")

# Inject dummy historical data for feed if empty
cursor.execute("SELECT COUNT(*) FROM feed_financials")
feed_count = cursor.fetchone()[0]
if feed_count == 0:
    import datetime as _dt2
    import random as _rand2
    _today2 = _dt2.date.today()
    for _i in range(30, 0, -1):
        _d = _today2 - _dt2.timedelta(days=_i)
        _kg = round(_rand2.uniform(320, 420), 1)
        _price = round(_rand2.uniform(4100, 4500), 0)
        _cost = _kg * _price
        cursor.execute(
            "INSERT INTO feed_financials (date, total_kg, price_per_kg, estimated_cost) VALUES (?, ?, ?, ?)",
            (_d.strftime("%Y-%m-%d"), _kg, _price, _cost)
        )

cursor.execute("""
CREATE TABLE IF NOT EXISTS milk_financials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT UNIQUE,
    total_liters REAL,
    price_per_liter REAL,
    estimated_revenue REAL
)
""")

# Inject dummy historical data for the last 30 days if empty
cursor.execute("SELECT COUNT(*) FROM milk_financials")
count = cursor.fetchone()[0]
if count == 0:
    import datetime
    import random
    today = datetime.date.today()
    for i in range(30, 0, -1):
        d = today - datetime.timedelta(days=i)
        liters = round(random.uniform(280, 340), 1)
        price = 4100.0  # Dummy price around normal market (or anything like 6000-7000 depending on actual milk price, we'll use 6500)
        revenue = liters * 6500.0
        cursor.execute(
            "INSERT INTO milk_financials (date, total_liters, price_per_liter, estimated_revenue) VALUES (?, ?, ?, ?)",
            (d.strftime("%Y-%m-%d"), liters, 6500.0, revenue)
        )

conn.commit()
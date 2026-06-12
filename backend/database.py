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

conn.commit()
import sqlite3
import threading
import os

_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mooos.db")

conn = sqlite3.connect(
    _DB_PATH,
    check_same_thread=False
)

# Thread lock to prevent SQLite cursor conflicts between
# the Telegram bot daemon thread and FastAPI request threads
db_lock = threading.Lock()


def db_fetch_all(sql: str, params: tuple = ()):
    """Thread-safe fetchall helper — uses a fresh cursor per call."""
    with db_lock:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()


def db_fetch_one(sql: str, params: tuple = ()):
    """Thread-safe fetchone helper — uses a fresh cursor per call."""
    with db_lock:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchone()


def db_execute(sql: str, params: tuple = ()):
    """Thread-safe execute + commit helper — uses a fresh cursor per call."""
    with db_lock:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        return cur.lastrowid

cursor = conn.cursor()

# ==========================================
# CORE TABLES
# ==========================================

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


# ==========================================
# COLUMN MIGRATIONS (backward compat)
# ==========================================

cursor.execute("PRAGMA table_info(cows)")
cows_cols = [row[1] for row in cursor.fetchall()]
if "feed_qty_needed" not in cows_cols:
    cursor.execute("ALTER TABLE cows ADD COLUMN feed_qty_needed REAL DEFAULT 0")
if "barn" not in cows_cols:
    cursor.execute("ALTER TABLE cows ADD COLUMN barn TEXT")
if "hash_id" not in cows_cols:
    cursor.execute("ALTER TABLE cows ADD COLUMN hash_id TEXT")
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
    cursor.execute("ALTER TABLE members ADD COLUMN iuran_wajib REAL DEFAULT 200000.0")
if "iuran_pokok" not in members_cols:
    cursor.execute("ALTER TABLE members ADD COLUMN iuran_pokok REAL DEFAULT 1500000.0")
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


# ==========================================
# KOPERASI CONFIG TABLE (admin-editable)
# ==========================================

cursor.execute("""
CREATE TABLE IF NOT EXISTS koperasi_config (
    key TEXT PRIMARY KEY,
    value REAL,
    label TEXT
)
""")

# Seed default config if empty
cursor.execute("SELECT COUNT(*) FROM koperasi_config")
if cursor.fetchone()[0] == 0:
    defaults = [
        # Bagi hasil
        ("bagi_hasil_koperasi",   0.6,       "Persentase Bagi Hasil Koperasi"),
        ("bagi_hasil_pemilik",    0.4,       "Persentase Bagi Hasil Pemilik"),
        # Harga produk
        ("harga_susu_per_liter",  6500.0,    "Harga Susu per Liter (Rp)"),
        ("harga_pupuk_per_kg",    5000.0,    "Harga Pupuk per Kg (Rp)"),
        # Produksi per sapi per hari
        ("produksi_susu_per_hari", 15.0,     "Produksi Susu per Sapi per Hari (liter)"),
        ("produksi_limbah_per_hari", 10.0,   "Produksi Limbah Segar per Sapi per Hari (kg)"),
        ("rasio_fermentasi",       0.6,      "Rasio Fermentasi (segar → pupuk jadi)"),
        # Iuran anggota
        ("simpanan_pokok",         1500000.0, "Simpanan Pokok per Anggota (Rp, sekali seumur hidup)"),
        ("simpanan_wajib_per_sapi", 200000.0, "Simpanan Wajib per Sapi per Bulan (Rp)"),
        # Biaya operasional
        ("pakan_per_sapi",         750000.0,  "Biaya Pakan per Sapi per Bulan (Rp)"),
        ("jumlah_pekerja",         5.0,       "Jumlah Pekerja (2 Kandang A + 2 Kandang B + 1 Admin)"),
        ("gaji_per_pekerja",       3800000.0, "Gaji per Pekerja per Bulan (Rp)"),
        ("biaya_karung",           350000.0,  "Biaya Karung per Bulan (Rp)"),
        ("biaya_fermentasi_em4",   202000.0,  "Biaya Fermentasi EM4 per Bulan (Rp)"),
        ("biaya_distribusi_susu",  800000.0,  "Biaya Distribusi Susu per Bulan (Rp)"),
        ("biaya_utilitas",         500000.0,  "Biaya Utilitas per Bulan (Rp)"),
    ]
    for key, value, label in defaults:
        cursor.execute(
            "INSERT INTO koperasi_config (key, value, label) VALUES (?, ?, ?)",
            (key, value, label)
        )


# ==========================================
# FINANCIAL TABLES
# ==========================================

cursor.execute("""
CREATE TABLE IF NOT EXISTS feed_financials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT UNIQUE,
    total_kg REAL,
    price_per_kg REAL,
    estimated_cost REAL
)
""")

# Migrasi kolom estimated_cost jika tabel sudah lama
cursor.execute("PRAGMA table_info(feed_financials)")
ff_cols = [row[1] for row in cursor.fetchall()]
if "estimated_cost" not in ff_cols:
    cursor.execute("ALTER TABLE feed_financials ADD COLUMN estimated_cost REAL")
    if "estimated_expense" in ff_cols:
        cursor.execute("UPDATE feed_financials SET estimated_cost = estimated_expense")

# Inject dummy data for feed_financials (sesuai model bisnis: 30 sapi × Rp 750.000/bulan)
cursor.execute("SELECT COUNT(*) FROM feed_financials")
feed_count = cursor.fetchone()[0]
if feed_count == 0:
    import datetime as _dt2
    import random as _rand2
    _today2 = _dt2.date.today()
    # 30 sapi × ~25kg pakan/hari = ~750 kg/hari, biaya = 750.000/sapi/bulan ÷ 30 = 25.000/sapi/hari
    # Harga pakan ~Rp 1.000/kg → 750kg × Rp 1.000 = Rp 750.000/hari
    for _i in range(30, 0, -1):
        _d = _today2 - _dt2.timedelta(days=_i)
        _kg = round(_rand2.uniform(700, 800), 1)   # ~750 kg/hari total (30 sapi)
        _price = round(_rand2.uniform(950, 1050), 0) # ~Rp 1.000/kg
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

# Inject dummy data for milk_financials (30 sapi × 15 liter/hari × Rp 6.500)
cursor.execute("SELECT COUNT(*) FROM milk_financials")
count = cursor.fetchone()[0]
if count == 0:
    import datetime
    import random
    today = datetime.date.today()
    for i in range(30, 0, -1):
        d = today - datetime.timedelta(days=i)
        # 30 sapi × 15 liter = 450 liter/hari ± variasi
        liters = round(random.uniform(420, 480), 1)
        price = 6500.0
        revenue = liters * price
        cursor.execute(
            "INSERT INTO milk_financials (date, total_liters, price_per_liter, estimated_revenue) VALUES (?, ?, ?, ?)",
            (d.strftime("%Y-%m-%d"), liters, price, revenue)
        )

# ==========================================
# WASTE & FERTILIZER TABLES
# ==========================================

cursor.execute("""
CREATE TABLE IF NOT EXISTS waste_financials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT UNIQUE,
    total_kg_fertilizer REAL,
    price_per_kg REAL,
    estimated_revenue REAL
)
""")

# Inject dummy data for waste_financials
# 30 sapi × 10 kg segar/hari = 300 kg segar → 180 kg pupuk/hari (rasio 0.6)
# Harga Rp 5.000/kg → revenue = 180 × 5.000 = 900.000/hari
cursor.execute("SELECT COUNT(*) FROM waste_financials")
if cursor.fetchone()[0] == 0:
    import datetime
    import random
    today = datetime.date.today()
    for i in range(30, 0, -1):
        d = today - datetime.timedelta(days=i)
        # Pupuk jadi setelah fermentasi: ~180 kg/hari ± variasi
        fertilizer = round(random.uniform(160, 200), 1)
        price = 5000.0
        revenue = fertilizer * price
        cursor.execute(
            "INSERT INTO waste_financials (date, total_kg_fertilizer, price_per_kg, estimated_revenue) VALUES (?, ?, ?, ?)",
            (d.strftime("%Y-%m-%d"), fertilizer, price, revenue)
        )

cursor.execute("""
CREATE TABLE IF NOT EXISTS waste_processing (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date_collected TEXT,
    kg_amount REAL,
    status TEXT,
    ready_date TEXT
)
""")

# Inject dummy active batches for waste_processing
cursor.execute("SELECT COUNT(*) FROM waste_processing")
if cursor.fetchone()[0] == 0:
    import datetime
    today = datetime.date.today()
    for i in range(1, 15, 3):
        d_collected = today - datetime.timedelta(days=i)
        d_ready = d_collected + datetime.timedelta(days=14)
        status = "FERMENTING" if d_ready > today else "READY"
        # 30 sapi × 10 kg/hari = 300 kg segar per batch
        cursor.execute(
            "INSERT INTO waste_processing (date_collected, kg_amount, status, ready_date) VALUES (?, ?, ?, ?)",
            (d_collected.strftime("%Y-%m-%d"), 300.0, status, d_ready.strftime("%Y-%m-%d"))
        )

cursor.execute("""
CREATE TABLE IF NOT EXISTS operational_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT,
    category TEXT,
    description TEXT,
    amount REAL,
    type TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS feed_price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT UNIQUE,
    price_per_kg REAL
)
""")

# Inject dummy historical data for feed_price_history
cursor.execute("SELECT COUNT(*) FROM feed_price_history")
if cursor.fetchone()[0] == 0:
    import datetime
    import random
    today = datetime.date.today()
    for i in range(30, 0, -1):
        d = today - datetime.timedelta(days=i)
        price = round(random.uniform(950, 1100), 0)
        cursor.execute(
            "INSERT INTO feed_price_history (date, price_per_kg) VALUES (?, ?)",
            (d.strftime("%Y-%m-%d"), price)
        )

conn.commit()
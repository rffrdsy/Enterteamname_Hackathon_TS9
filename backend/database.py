"""
Database initialization, seeding, and legacy helpers.
Uses SQLAlchemy ORM from models.py.
"""
import datetime
import random
from models import (
    Base, engine, Session, get_session,
    Member, Cow, FeedOrder, FeedOrderRecipient, MessageRef,
    KoperasiConfig, FeedFinancial, MilkFinancial,
    WasteFinancial, WasteProcessing, OperationalTransaction,
    FeedPriceHistory, DailyKandangLog,
)

# ──────────────────────────────────────────────────────────────
# CREATE ALL TABLES
# ──────────────────────────────────────────────────────────────
Base.metadata.create_all(engine)

# ──────────────────────────────────────────────────────────────
# LEGACY HELPERS (for backward compat during transition)
# These wrap ORM sessions so old code that calls db_fetch_all()
# still works without changes.
# ──────────────────────────────────────────────────────────────
import threading
db_lock = threading.Lock()

# Keep a raw connection for any code that still needs it
import sqlite3, os
_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mooos.db")
conn = sqlite3.connect(_DB_PATH, check_same_thread=False)


def db_fetch_all(sql: str, params: tuple = ()):
    """Thread-safe fetchall helper — raw SQL."""
    with db_lock:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()


def db_fetch_one(sql: str, params: tuple = ()):
    """Thread-safe fetchone helper — raw SQL."""
    with db_lock:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchone()


def db_execute(sql: str, params: tuple = ()):
    """Thread-safe execute + commit helper — raw SQL."""
    with db_lock:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        return cur.lastrowid


# ──────────────────────────────────────────────────────────────
# SEED: KOPERASI CONFIG
# ──────────────────────────────────────────────────────────────
session = get_session()

if session.query(KoperasiConfig).count() == 0:
    defaults = [
        ("bagi_hasil_koperasi",    0.6,       "Persentase Bagi Hasil Koperasi"),
        ("bagi_hasil_pemilik",     0.4,       "Persentase Bagi Hasil Pemilik"),
        ("harga_susu_per_liter",   6500.0,    "Harga Susu per Liter (Rp)"),
        ("harga_pupuk_per_kg",     5000.0,    "Harga Pupuk per Kg (Rp)"),
        ("produksi_susu_per_hari", 15.0,      "Produksi Susu per Sapi per Hari (liter)"),
        ("produksi_limbah_per_hari", 10.0,    "Produksi Limbah Segar per Sapi per Hari (kg)"),
        ("rasio_fermentasi",       0.6,       "Rasio Fermentasi (segar → pupuk jadi)"),
        ("simpanan_pokok",         1500000.0, "Simpanan Pokok per Anggota (Rp, sekali seumur hidup)"),
        ("simpanan_wajib_per_sapi", 200000.0, "Simpanan Wajib per Sapi per Bulan (Rp)"),
        ("pakan_per_sapi",         750000.0,  "Biaya Pakan per Sapi per Bulan (Rp)"),
        ("jumlah_pekerja",         5.0,       "Jumlah Pekerja (2 Kandang A + 2 Kandang B + 1 Admin)"),
        ("gaji_per_pekerja",       3800000.0, "Gaji per Pekerja per Bulan (Rp)"),
        ("biaya_karung",           350000.0,  "Biaya Karung per Bulan (Rp)"),
        ("biaya_fermentasi_em4",   202000.0,  "Biaya Fermentasi EM4 per Bulan (Rp)"),
        ("biaya_distribusi_susu",  800000.0,  "Biaya Distribusi Susu per Bulan (Rp)"),
        ("biaya_utilitas",         500000.0,  "Biaya Utilitas per Bulan (Rp)"),
    ]
    for key, value, label in defaults:
        session.add(KoperasiConfig(key=key, value=value, label=label))
    session.commit()


# ──────────────────────────────────────────────────────────────
# SEED: MEMBERS (20 penitip + 2 penanggungjawab)
# ──────────────────────────────────────────────────────────────

if session.query(Member).count() == 0:
    penitip_names = [
        "Ahmad Sudirman", "Budi Santoso", "Cahyo Wibowo", "Dedi Kurniawan",
        "Eko Prasetyo", "Fajar Hidayat", "Gunawan Setiawan", "Hadi Purnomo",
        "Irwan Saputra", "Joko Susilo", "Kartono Wijaya", "Lukman Hakim",
        "Mulyono Haryanto", "Narto Sugiarto", "Oka Permana", "Prayitno Utomo",
        "Qomar Ridwan", "Rudi Hartono", "Slamet Raharjo", "Taufik Ismail",
    ]
    for i, name in enumerate(penitip_names, start=1):
        session.add(Member(
            name=name,
            nik=f"33050219{70+i:02d}0101{i:04d}",
            phone=f"08{random.randint(1000000000, 9999999999)}",
            alamat=f"Desa Harapan RT {random.randint(1,10):02d}/RW {random.randint(1,5):02d}",
            role="Penitip Ternak",
            iuran_pokok=1500000.0,
            iuran_wajib=200000.0,
        ))

    # 2 Penanggungjawab (sesuai config: 2 kandang A + 2 kandang B, tapi PJ hanya 2)
    session.add(Member(
        name="Abyasa (PJ Kandang A)", nik="3305021990010121",
        phone="081234567890", alamat="Kantor Koperasi",
        role="Penanggungjawab Ternak", barn="A",
        iuran_pokok=1500000.0, iuran_wajib=0.0,
    ))
    session.add(Member(
        name="Axel (PJ Kandang B)", nik="3305021991010122",
        phone="081234567891", alamat="Kantor Koperasi",
        role="Penanggungjawab Ternak", barn="B",
        iuran_pokok=1500000.0, iuran_wajib=0.0,
    ))
    session.commit()


# ──────────────────────────────────────────────────────────────
# SEED: COWS (30 ekor, distributed across 20 owners)
# ──────────────────────────────────────────────────────────────
today = datetime.date.today()

if session.query(Cow).count() == 0:
    import uuid as _uuid
    penitip_ids = [m.id for m in session.query(Member).filter_by(role="Penitip Ternak").all()]

    jenis_options = ["Perah", "Pedaging", "Perah"]
    barns = ["A", "B"]
    cow_index = 0

    for i in range(30):
        owner_id = penitip_ids[i % len(penitip_ids)]
        barn = barns[i % 2]
        jenis = jenis_options[i % 3]
        cow_code = f"S{i+1:03d}"
        hash_id = _uuid.uuid4().hex[:8]

        session.add(Cow(
            cow_code=cow_code,
            owner_id=owner_id,
            weight=round(random.uniform(350, 550), 1),
            status="AVAILABLE",
            caretaker="ABYASA" if barn == "A" else "AXEL",
            barn=barn,
            hash_id=hash_id,
            jenis=jenis,
            umur=f"{random.randint(2,8)} tahun",
            tgl_masuk=(today - datetime.timedelta(days=random.randint(30, 365))).strftime("%Y-%m-%d"),
            lactate_status="Laktasi" if jenis == "Perah" else "Kering",
            litre_milked_today=round(random.uniform(12, 18), 1) if jenis == "Perah" else 0.0,
        ))
    session.commit()


# ──────────────────────────────────────────────────────────────
# SEED: DUMMY FINANCIAL DATA (30 days)
# ──────────────────────────────────────────────────────────────
today = datetime.date.today()

# Feed financials
if session.query(FeedFinancial).count() == 0:
    for i in range(30, 0, -1):
        d = today - datetime.timedelta(days=i)
        kg = round(random.uniform(700, 800), 1)
        price = round(random.uniform(950, 1050), 0)
        session.add(FeedFinancial(
            date=d.strftime("%Y-%m-%d"),
            total_kg=kg,
            price_per_kg=price,
            estimated_cost=kg * price,
        ))
    session.commit()

# Milk financials
if session.query(MilkFinancial).count() == 0:
    for i in range(30, 0, -1):
        d = today - datetime.timedelta(days=i)
        liters = round(random.uniform(420, 480), 1)
        price = 6500.0
        session.add(MilkFinancial(
            date=d.strftime("%Y-%m-%d"),
            total_liters=liters,
            price_per_liter=price,
            estimated_revenue=liters * price,
        ))
    session.commit()

# Waste financials
if session.query(WasteFinancial).count() == 0:
    for i in range(30, 0, -1):
        d = today - datetime.timedelta(days=i)
        fertilizer = round(random.uniform(160, 200), 1)
        price = 5000.0
        session.add(WasteFinancial(
            date=d.strftime("%Y-%m-%d"),
            total_kg_fertilizer=fertilizer,
            price_per_kg=price,
            estimated_revenue=fertilizer * price,
        ))
    session.commit()

# Waste processing batches
if session.query(WasteProcessing).count() == 0:
    for i in range(1, 15, 3):
        d_collected = today - datetime.timedelta(days=i)
        d_ready = d_collected + datetime.timedelta(days=14)
        status = "FERMENTING" if d_ready > today else "READY"
        session.add(WasteProcessing(
            date_collected=d_collected.strftime("%Y-%m-%d"),
            kg_amount=300.0,
            status=status,
            ready_date=d_ready.strftime("%Y-%m-%d"),
        ))
    session.commit()

# Feed price history
if session.query(FeedPriceHistory).count() == 0:
    for i in range(30, 0, -1):
        d = today - datetime.timedelta(days=i)
        price = round(random.uniform(950, 1100), 0)
        session.add(FeedPriceHistory(
            date=d.strftime("%Y-%m-%d"),
            price_per_kg=price,
        ))
    session.commit()

# Close seed session
Session.remove()
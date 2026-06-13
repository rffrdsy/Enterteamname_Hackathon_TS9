import time
import uuid
import threading
import sqlite3
import uvicorn
import os
import mimetypes
import qrcode
import datetime
from io import BytesIO

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, FileResponse
from pydantic import BaseModel
from typing import Optional
from database import conn

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

from telegram_bot import (
    start_bot,
    send_new_cow,
    send_sell_scan_request,
    send_feed_order,
    set_bot_status_ref,
)

from config import (
    ABYASA_ID,
    AXEL_ID,
    ELISA_ID,
    RAFIF_ID,
    BARN_TELEGRAM_IDS,
    BOT_USERNAME
)

from spk_generator import generate_spk_pdf

# Folder penyimpanan foto sapi
FOTO_DIR = os.path.join(os.path.dirname(__file__), "foto_sapi")
os.makedirs(FOTO_DIR, exist_ok=True)

# Folder penyimpanan QR code sapi
QR_DIR = os.path.join(os.path.dirname(__file__), "qr_sapi")
os.makedirs(QR_DIR, exist_ok=True)

app = FastAPI(title="Mooos API", version="1.0.0")

# Global bot status tracker — updated by telegram_bot thread
BOT_STATUS = {
    "connected": False,
    "last_update_ts": None,   # Unix timestamp of last Telegram update received
    "start_ts": time.time(),  # When the server started
}

# Allow frontend (any localhost port) to call this backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8080",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8080",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CowRequest(BaseModel):
    cow_id: str
    owner: str = "Koperasi"
    owner_id: Optional[int] = None
    weight: Optional[float] = None
    umur: Optional[str] = None
    jenis: Optional[str] = None
    tgl_masuk: Optional[str] = None
    lactate_status: Optional[str] = None

class SellCowRequest(BaseModel):
    cow_code: str


class UpdateCowDetail(BaseModel):
    jenis: Optional[str] = None
    umur: Optional[str] = None
    tgl_masuk: Optional[str] = None
    deskripsi: Optional[str] = None
    lactate_status: Optional[str] = None
    litre_milked_today: Optional[float] = None
    weight: Optional[float] = None


class MemberRequest(BaseModel):
    name: str
    nik: str = ""
    phone: str = ""
    alamat: str = ""
    role: str = "Penitip Ternak"


@app.get("/")
def home():
    return {"status": "running"}


@app.get("/health")
def health_check():
    """Live system health check for the dashboard Status Sistem widget."""
    # 1. Database check — a simple query to verify the connection is alive
    db_healthy = False
    try:
        result = db_fetch_one("SELECT COUNT(*) FROM cows")
        db_healthy = result is not None
    except Exception:
        db_healthy = False

    # 2. Network / internet check — we report the local backend itself as "online"
    #    The JS frontend can determine its own online/offline state via navigator.onLine
    online = True  # Backend is reachable ↔ it's "online" from the client's perspective

    # 3. Telegram bot status
    bot_connected = BOT_STATUS["connected"]
    last_update_ts = BOT_STATUS["last_update_ts"]

    # Format "Sinkronisasi Terakhir"
    if last_update_ts is not None:
        delta = int(time.time() - last_update_ts)
        if delta < 60:
            last_sync = f"{delta} detik lalu"
        elif delta < 3600:
            last_sync = f"{delta // 60} menit lalu"
        elif delta < 86400:
            last_sync = f"{delta // 3600} jam lalu"
        else:
            last_sync = f"{delta // 86400} hari lalu"
    else:
        # Bot has never received an update since server start — show server uptime
        uptime_s = int(time.time() - BOT_STATUS["start_ts"])
        last_sync = f"Server baru menyala {uptime_s // 60} menit lalu"

    return {
        "online": online,
        "telegram_bot": {
            "connected": bot_connected,
            "status": "Connected" if bot_connected else "Disconnected",
        },
        "database": {
            "healthy": db_healthy,
            "status": "Healthy" if db_healthy else "Error",
        },
        "last_sync": last_sync,
    }



@app.get("/members")
def get_members():
    """Hanya Penitip Ternak."""
    rows = db_fetch_all(
        """
        SELECT m.id, m.name, m.nik, m.phone, m.alamat, m.role, m.barn, m.iuran_wajib, m.iuran_pokok,
               (SELECT COUNT(*) FROM cows c WHERE c.owner_id = m.id) AS cow_count
        FROM members m
        WHERE m.role != 'Penanggungjawab Ternak'
        """
    )
    result = []
    for r in rows:
        result.append({
            "id": r[0],
            "name": r[1],
            "nik": r[2],
            "phone": r[3],
            "alamat": r[4],
            "role": r[5] or "Penitip Ternak",
            "barn": r[6],
            "iuran_wajib": r[7] or 50000.0,
            "iuran_pokok": r[8] or 100000.0,
            "cow_count": r[9] or 0,
        })
    return result


@app.get("/members/{member_id}")
def get_member_detail(member_id: int):
    """Detail Penitip Ternak — menampilkan sapi yang DIMILIKI."""
    row = db_fetch_one(
        """
        SELECT m.id, m.name, m.nik, m.phone, m.alamat, m.role, m.barn, m.iuran_wajib, m.iuran_pokok
        FROM members m
        WHERE m.id = ? AND m.role != 'Penanggungjawab Ternak'
        """,
        (member_id,)
    )
    if not row:
        raise HTTPException(status_code=404, detail="Penitip tidak ditemukan.")

    member_data = {
        "id": row[0],
        "name": row[1],
        "nik": row[2],
        "phone": row[3],
        "alamat": row[4],
        "role": row[5] or "Penitip Ternak",
        "barn": row[6],
        "iuran_wajib": row[7] or 50000.0,
        "iuran_pokok": row[8] or 100000.0,
        "cows": []
    }

    cows = db_fetch_all(
        """
        SELECT id, cow_code, weight, status, barn, jenis, lactate_status, litre_milked_today
        FROM cows WHERE owner_id = ?
        """,
        (member_id,)
    )
    for c in cows:
        member_data["cows"].append({
            "id": c[0], "cow_code": c[1], "weight": c[2], "status": c[3],
            "barn": c[4], "jenis": c[5],
            "lactate_status": c[6] or "Kering",
            "litre_milked_today": c[7] or 0.0
        })

    return member_data


@app.get("/penanggungjawab")
def get_penanggungjawab():
    """Semua Penanggungjawab Ternak beserta jumlah sapi di kandangnya."""
    rows = db_fetch_all(
        """
        SELECT m.id, m.name, m.nik, m.phone, m.alamat, m.role, m.barn,
               (SELECT COUNT(*) FROM cows c WHERE c.barn = m.barn AND m.barn IS NOT NULL) AS cow_count
        FROM members m
        WHERE m.role = 'Penanggungjawab Ternak'
        """
    )
    result = []
    for r in rows:
        result.append({
            "id": r[0],
            "name": r[1],
            "nik": r[2],
            "phone": r[3],
            "alamat": r[4],
            "role": r[5],
            "barn": r[6],
            "cow_count": r[7] or 0,
        })
    return result


@app.get("/penanggungjawab/{pj_id}")
def get_penanggungjawab_detail(pj_id: int):
    """Detail Penanggungjawab Ternak — menampilkan sapi yang ADA DI KANDANGNYA."""
    row = db_fetch_one(
        """
        SELECT m.id, m.name, m.nik, m.phone, m.alamat, m.role, m.barn
        FROM members m
        WHERE m.id = ? AND m.role = 'Penanggungjawab Ternak'
        """,
        (pj_id,)
    )
    if not row:
        raise HTTPException(status_code=404, detail="Penanggungjawab tidak ditemukan.")

    pj_data = {
        "id": row[0],
        "name": row[1],
        "nik": row[2],
        "phone": row[3],
        "alamat": row[4],
        "role": row[5],
        "barn": row[6],
        "cows": []
    }

    if row[6]:  # barn
        cows = db_fetch_all(
            """
            SELECT c.id, c.cow_code, c.weight, c.status, c.jenis,
                   c.lactate_status, c.litre_milked_today, m2.name AS owner_name
            FROM cows c
            LEFT JOIN members m2 ON c.owner_id = m2.id
            WHERE c.barn = ?
            ORDER BY c.cow_code
            """,
            (row[6],)
        )
        for c in cows:
            pj_data["cows"].append({
                "id": c[0], "cow_code": c[1], "weight": c[2], "status": c[3],
                "jenis": c[4],
                "lactate_status": c[5] or "Kering",
                "litre_milked_today": c[6] or 0.0,
                "owner_name": c[7] or "—"
            })

    return pj_data


@app.post("/members")
def add_member(data: MemberRequest):
    try:
        member_id = db_execute(
            "INSERT INTO members(name, nik, phone, alamat, role) VALUES (?, ?, ?, ?, ?)",
            (data.name, data.nik, data.phone, data.alamat, data.role)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "message": "Anggota berhasil ditambahkan",
        "id": member_id,
        "name": data.name,
        "role": data.role,
    }


@app.post("/new-cow")
def new_cow(data: CowRequest):
    hash_id = uuid.uuid4().hex[:8]
    try:
        db_execute(
            """INSERT INTO cows(
                cow_code, status, hash_id, owner_id,
                weight, umur, jenis, tgl_masuk, lactate_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data.cow_id, "LOOKING_FOR_CARETAKER", hash_id, data.owner_id,
                data.weight, data.umur, data.jenis, data.tgl_masuk, data.lactate_status
            )
        )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail=f"Sapi dengan ID '{data.cow_id}' sudah ada.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    send_new_cow(data.cow_id, data.owner)

    # Generate QR code
    qr_url = f"https://t.me/{BOT_USERNAME}?start=CONFIRM_{data.cow_id}_{hash_id}"
    qr_img = qrcode.make(qr_url)
    qr_path = os.path.join(QR_DIR, f"{data.cow_id}.png")
    qr_img.save(qr_path)

    return {
        "message": "Sapi disimpan dan notifikasi dikirim",
        "cow_id": data.cow_id,
        "hash_id": hash_id,
        "qr_url": f"http://localhost:8000/qr/{data.cow_id}"
    }


@app.get("/qr/{cow_code}")
def get_qr_code(cow_code: str):
    qr_path = os.path.join(QR_DIR, f"{cow_code}.png")
    if not os.path.exists(qr_path):
        # Generate on-the-fly if missing
        row = db_fetch_one("SELECT hash_id FROM cows WHERE cow_code = ?", (cow_code,))
        if not row:
            raise HTTPException(status_code=404, detail="Sapi tidak ditemukan")
        hash_id = row[0]
        qr_url = f"https://t.me/{BOT_USERNAME}?start=CONFIRM_{cow_code}_{hash_id}"
        qr_img = qrcode.make(qr_url)
        qr_img.save(qr_path)
    return FileResponse(qr_path, media_type="image/png")


@app.get("/cows")
def get_cows():
    rows = db_fetch_all(
        """
        SELECT c.id, c.cow_code, c.owner_id, c.weight, c.status, c.caretaker,
               c.feed_qty_needed, c.barn, c.hash_id, c.jenis, m.name AS owner_name,
               c.lactate_status, c.litre_milked_today
        FROM cows c
        LEFT JOIN members m ON c.owner_id = m.id
        """
    )
    result = []
    for r in rows:
        result.append({
            "id": r[0],
            "cow_code": r[1],
            "owner_id": r[2],
            "weight": r[3],
            "status": r[4],
            "caretaker": r[5],
            "feed_qty_needed": r[6],
            "barn": r[7],
            "hash_id": r[8],
            "jenis": r[9],
            "owner_name": r[10],
            "lactate_status": r[11] or "Kering",
            "litre_milked_today": r[12] or 0.0,
        })
    return result


@app.get("/cows/{cow_code}/foto")
@app.head("/cows/{cow_code}/foto")
def get_foto(cow_code: str):
    """
    Serve foto sapi dari filesystem. Mendukung GET dan HEAD request.
    """
    row = db_fetch_one("SELECT foto_path FROM cows WHERE cow_code = ?", (cow_code,))
    if not row:
        raise HTTPException(status_code=404, detail=f"Sapi '{cow_code}' tidak ditemukan.")

    foto_path = row[0]
    if not foto_path or not os.path.isfile(foto_path):
        raise HTTPException(status_code=404, detail="Foto belum tersedia.")

    mime, _ = mimetypes.guess_type(foto_path)
    return FileResponse(foto_path, media_type=mime or "image/jpeg")


@app.post("/sell-cow")
def sell_cow(data: SellCowRequest):
    row = db_fetch_one(
        "SELECT cow_code, status, barn, hash_id FROM cows WHERE cow_code = ?",
        (data.cow_code,)
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"Sapi '{data.cow_code}' tidak ditemukan.")

    cow_code, status, barn, hash_id = row

    blocked_statuses = ("WAITING_CONFIRMATION", "SOLD")
    if status in blocked_statuses:
        raise HTTPException(status_code=400, detail=f"Sapi sudah dalam status '{status}', tidak bisa diproses ulang.")

    if not hash_id:
        raise HTTPException(status_code=400, detail="Sapi tidak memiliki hash_id. Daftarkan ulang sapi ini.")

    if not barn:
        raise HTTPException(status_code=400, detail="Sapi belum memiliki lokasi kandang (belum di-accept oleh pengurus).")

    pic_id = BARN_TELEGRAM_IDS.get(barn.upper())
    if not pic_id:
        raise HTTPException(status_code=400, detail=f"Tidak ada PIC untuk kandang '{barn}'.")

    db_execute("UPDATE cows SET status = ? WHERE cow_code = ?", ("WAITING_CONFIRMATION", cow_code))
    send_sell_scan_request(pic_id, cow_code, barn.upper(), hash_id)

    return {"message": "Notifikasi dikirim ke PIC kandang", "cow_code": cow_code, "barn": barn.upper(), "pic_telegram_id": pic_id}


@app.post("/buy-feed")
def buy_feed():
    row = db_fetch_one(
        "SELECT COALESCE(SUM(feed_qty_needed), 0) FROM cows WHERE status NOT IN ('SOLD', 'REJECTED')"
    )
    total_qty = (row[0] if row else 0) or 100
    price_per_kg = 5000.0
    po_code = f"PO-{int(time.time())}"

    db_execute(
        "INSERT INTO feed_orders(po_code, qty, price_per_kg, status) VALUES (?, ?, ?, ?)",
        (po_code, total_qty, price_per_kg, "PENDING")
    )

    suppliers = [ELISA_ID, RAFIF_ID]
    for tid in suppliers:
        db_execute(
            "INSERT INTO feed_order_recipients(po_code, telegram_id) VALUES (?, ?)",
            (po_code, tid)
        )

    for chat_id in suppliers:
        send_feed_order(chat_id, po_code, total_qty, price_per_kg)

    return {
        "message": "Feed order dikirim",
        "po_code": po_code,
        "qty_kg": total_qty,
        "price_per_kg": price_per_kg,
        "total_estimasi": total_qty * price_per_kg
    }



@app.get("/feed-orders")
def get_feed_orders():
    """
    Ambil semua feed orders (PO pakan) untuk ditampilkan di halaman transaksi keuangan.
    """
    rows = db_fetch_all(
        """
        SELECT fo.id, fo.po_code, fo.qty, fo.price_per_kg, fo.status, fo.supplier
        FROM feed_orders fo
        ORDER BY fo.id DESC
        """
    )
    result = []
    for r in rows:
        result.append({
            "id": r[0],
            "po_code": r[1],
            "qty": r[2],
            "price_per_kg": r[3] or 5000,
            "status": r[4] or "PENDING",
            "supplier": r[5],
        })
    return result


# =============================================================
# MILK PRODUCTION & FINANCIALS
# =============================================================

@app.get("/milk/summary")
def get_milk_summary():
    # 1. Total hari ini dari cows (Hanya yang Laktasi atau ada susu)
    cows = db_fetch_all("SELECT id, cow_code, lactate_status, litre_milked_today FROM cows WHERE lactate_status = 'Laktasi' OR litre_milked_today > 0 ORDER BY cow_code")
    total_today = sum((c[3] or 0.0) for c in cows)
    
    cow_details = []
    for c in cows:
        cow_details.append({
            "id": c[0],
            "cow_code": c[1],
            "lactate_status": c[2] or "Kering",
            "litre_milked_today": c[3] or 0.0
        })
        
    # 2. Get past data
    past_logs = db_fetch_all("SELECT date, total_liters, estimated_revenue FROM milk_financials ORDER BY date DESC LIMIT 30")
    
    total_week = total_today
    total_month = total_today
    
    # Calculate for the past 6 days (to make a 7-day week)
    for row in past_logs[:6]:
        total_week += row[1] or 0.0
        
    # Calculate for the past 29 days (to make a 30-day month)
    for row in past_logs[:29]:
        total_month += row[1] or 0.0
        
    # Latest price from DB
    latest_price = 6500.0
    if past_logs:
        latest_row = db_fetch_one("SELECT price_per_liter FROM milk_financials ORDER BY date DESC LIMIT 1")
        if latest_row and latest_row[0]:
            latest_price = latest_row[0]
            
    estimated_revenue_month = total_month * latest_price
    
    return {
        "total_today": round(total_today, 1),
        "total_week": round(total_week, 1),
        "total_month": round(total_month, 1),
        "latest_price": latest_price,
        "estimated_revenue_month": round(estimated_revenue_month, 1),
        "cows": cow_details,
        "history": [{"date": r[0], "total_liters": r[1]} for r in past_logs[::-1]]  # chronological for chart
    }

@app.post("/milk/financials")
def save_milk_financials(data: dict):
    # expect data: {"date": "YYYY-MM-DD", "total_liters": 100, "price_per_liter": 6500, "estimated_revenue": 650000}
    try:
        db_execute(
            """
            INSERT INTO milk_financials (date, total_liters, price_per_liter, estimated_revenue)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                total_liters = excluded.total_liters,
                price_per_liter = excluded.price_per_liter,
                estimated_revenue = excluded.estimated_revenue
            """,
            (data.get("date"), data.get("total_liters", 0), data.get("price_per_liter", 0), data.get("estimated_revenue", 0))
        )
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================
# SPK – Surat Penjualan Sapi
# =============================================================

def _get_cow_full(cow_code: str) -> dict:
    """Helper: ambil data lengkap sapi + nama pemilik."""
    row = db_fetch_one(
        """
        SELECT
            c.id, c.cow_code, c.owner_id, c.weight, c.status,
            c.caretaker, c.barn, c.jenis, c.umur, c.tgl_masuk,
            c.deskripsi, c.foto_path, c.lactate_status, c.litre_milked_today,
            m.name AS owner_name
        FROM cows c
        LEFT JOIN members m ON c.owner_id = m.id
        WHERE c.cow_code = ?
        """,
        (cow_code,)
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"Sapi '{cow_code}' tidak ditemukan.")
    return {
        "id":         row[0],
        "cow_code":   row[1],
        "owner_id":   row[2],
        "weight":     row[3],
        "status":     row[4],
        "caretaker":  row[5],
        "barn":       row[6],
        "jenis":      row[7],
        "umur":       row[8],
        "tgl_masuk":  row[9],
        "deskripsi":  row[10],
        "foto_path":  row[11],
        "lactate_status": row[12] or "Kering",
        "litre_milked_today": row[13] or 0.0,
        "owner_name": row[14],
    }


@app.get("/cows/{cow_code}/spk")
def preview_spk(cow_code: str):
    """
    Preview data SPK sapi dalam format JSON.
    Digunakan oleh admin koperasi untuk menampilkan detail sebelum download PDF.
    """
    return _get_cow_full(cow_code)


@app.put("/cows/{cow_code}")
def update_cow_detail(cow_code: str, data: UpdateCowDetail):
    if not db_fetch_one("SELECT id FROM cows WHERE cow_code = ?", (cow_code,)):
        raise HTTPException(status_code=404, detail=f"Sapi '{cow_code}' tidak ditemukan.")

    fields, values = [], []
    if data.jenis is not None:
        fields.append("jenis = ?"); values.append(data.jenis)
    if data.umur is not None:
        fields.append("umur = ?"); values.append(data.umur)
    if data.tgl_masuk is not None:
        fields.append("tgl_masuk = ?"); values.append(data.tgl_masuk)
    if data.deskripsi is not None:
        fields.append("deskripsi = ?"); values.append(data.deskripsi)
    if data.lactate_status is not None:
        fields.append("lactate_status = ?"); values.append(data.lactate_status)
    if data.litre_milked_today is not None:
        fields.append("litre_milked_today = ?"); values.append(data.litre_milked_today)
    if data.weight is not None:
        fields.append("weight = ?"); values.append(data.weight)

    if not fields:
        return {"message": "Tidak ada data yang diperbarui"}

    values.append(cow_code)
    db_execute(f"UPDATE cows SET {', '.join(fields)} WHERE cow_code = ?", tuple(values))
    return {"message": f"Detail sapi '{cow_code}' diperbarui"}


@app.delete("/cows/{cow_code}")
def delete_cow(cow_code: str):
    if not db_fetch_one("SELECT id FROM cows WHERE cow_code = ?", (cow_code,)):
        raise HTTPException(status_code=404, detail=f"Sapi '{cow_code}' tidak ditemukan.")
    
    db_execute("DELETE FROM cows WHERE cow_code = ?", (cow_code,))
    return {"message": f"Sapi '{cow_code}' berhasil dihapus", "cow_code": cow_code}


@app.post("/cows/{cow_code}/foto")
async def upload_foto(cow_code: str, foto: UploadFile = File(...)):
    if not db_fetch_one("SELECT id FROM cows WHERE cow_code = ?", (cow_code,)):
        raise HTTPException(status_code=404, detail=f"Sapi '{cow_code}' tidak ditemukan.")

    allowed = {"image/jpeg", "image/png", "image/webp"}
    if foto.content_type not in allowed:
        raise HTTPException(status_code=400, detail="Hanya file JPEG/PNG/WEBP yang diizinkan.")

    ext = foto.filename.rsplit(".", 1)[-1].lower() if "." in foto.filename else "jpg"
    save_path = os.path.join(FOTO_DIR, f"{cow_code}.{ext}")

    contents = await foto.read()
    with open(save_path, "wb") as f:
        f.write(contents)

    db_execute("UPDATE cows SET foto_path = ? WHERE cow_code = ?", (save_path, cow_code))
    return {"message": "Foto berhasil diupload.", "foto_path": save_path}


@app.get("/cows/{cow_code}/spk/pdf")
def download_spk_pdf(cow_code: str):
    """
    Generate dan download PDF Surat Penjualan Sapi (SPK) untuk sapi yang sudah SOLD.
    File langsung dikembalikan sebagai attachment — browser akan otomatis mendownload.
    """
    cow = _get_cow_full(cow_code)

    if cow["status"] != "SOLD":
        raise HTTPException(
            status_code=400,
            detail=f"SPK hanya bisa digenerate untuk sapi berstatus SOLD. Status saat ini: {cow['status']}"
        )

    pdf_bytes = generate_spk_pdf(cow)

    filename = f"SPK_{cow_code}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(pdf_bytes)),
        }
    )



# Inject BOT_STATUS reference so telegram_bot.py can update live health status
set_bot_status_ref(BOT_STATUS)

threading.Thread(
    target=start_bot,
    daemon=True
).start()



if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000
    )

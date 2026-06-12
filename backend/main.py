import time
import uuid
import threading
import sqlite3
import uvicorn
import os
import mimetypes

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, FileResponse
from pydantic import BaseModel
from typing import Optional
from database import conn, cursor

# Thread lock to prevent SQLite cursor conflicts between
# the Telegram bot daemon thread and FastAPI request threads
db_lock = threading.Lock()


def db_fetch_all(sql: str, params: tuple = ()):
    """Thread-safe fetchall helper."""
    with db_lock:
        cursor.execute(sql, params)
        return cursor.fetchall()


def db_fetch_one(sql: str, params: tuple = ()):
    """Thread-safe fetchone helper."""
    with db_lock:
        cursor.execute(sql, params)
        return cursor.fetchone()


def db_execute(sql: str, params: tuple = ()):
    """Thread-safe execute + commit helper."""
    with db_lock:
        cursor.execute(sql, params)
        conn.commit()
        return cursor.lastrowid

from telegram_bot import (
    start_bot,
    send_new_cow,
    send_sell_scan_request,
    send_feed_order
)

from config import (
    ABYASA_ID,
    AXEL_ID,
    ELISA_ID,
    RAFIF_ID,
    BARN_TELEGRAM_IDS
)

from spk_generator import generate_spk_pdf

# Folder penyimpanan foto sapi
FOTO_DIR = os.path.join(os.path.dirname(__file__), "foto_sapi")
os.makedirs(FOTO_DIR, exist_ok=True)

app = FastAPI(title="Mooos API", version="1.0.0")

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
    owner: str


class SellCowRequest(BaseModel):
    cow_code: str


class UpdateCowDetail(BaseModel):
    jenis: Optional[str] = None
    umur: Optional[str] = None
    tgl_masuk: Optional[str] = None
    deskripsi: Optional[str] = None


class MemberRequest(BaseModel):
    name: str
    nik: str = ""
    phone: str = ""
    alamat: str = ""
    role: str = "Penitip Ternak"


@app.get("/")
def home():
    return {"status": "running"}


@app.get("/members")
def get_members():
    rows = db_fetch_all(
        """
        SELECT m.id, m.name, m.nik, m.phone, m.alamat, m.role, m.barn,
               (SELECT COUNT(*) FROM cows c WHERE c.barn = m.barn AND m.barn IS NOT NULL) AS cow_count
        FROM members m
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
            "cow_count": r[7] or 0,
        })
    return result


@app.post("/members")
def add_member(data: MemberRequest):
    try:
        with db_lock:
            cursor.execute(
                """
                INSERT INTO members(name, nik, phone, alamat, role)
                VALUES (?, ?, ?, ?, ?)
                """,
                (data.name, data.nik, data.phone, data.alamat, data.role)
            )
            conn.commit()
            member_id = cursor.lastrowid
    except Exception as e:
        with db_lock:
            conn.rollback()
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
        cursor.execute(
            """
            INSERT INTO cows(
                cow_code,
                status,
                hash_id
            )
            VALUES (?, ?, ?)
            """,
            (
                data.cow_id,
                "LOOKING_FOR_CARETAKER",
                hash_id
            )
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        raise HTTPException(
            status_code=400,
            detail=f"Sapi dengan ID '{data.cow_id}' sudah ada."
        )
    except Exception as e:
        conn.rollback()
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    send_new_cow(
        data.cow_id,
        data.owner
    )

    return {
        "message": "Sapi disimpan dan notifikasi dikirim",
        "cow_id": data.cow_id,
        "hash_id": hash_id
    }


@app.get("/cows")
def get_cows():
    rows = db_fetch_all(
        """
        SELECT c.id, c.cow_code, c.owner_id, c.weight, c.status, c.caretaker,
               c.feed_qty_needed, c.barn, c.hash_id, c.jenis, m.name AS owner_name
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

    # Ambil data sapi
    cursor.execute(
        """
        SELECT cow_code, status, barn, hash_id
        FROM cows
        WHERE cow_code = ?
        """,
        (data.cow_code,)
    )
    row = cursor.fetchone()

    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"Sapi '{data.cow_code}' tidak ditemukan."
        )

    cow_code, status, barn, hash_id = row

    # Validasi status — tidak boleh proses ulang
    blocked_statuses = ("WAITING_CONFIRMATION", "SOLD")
    if status in blocked_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Sapi sudah dalam status '{status}', tidak bisa diproses ulang."
        )

    if not hash_id:
        raise HTTPException(
            status_code=400,
            detail="Sapi tidak memiliki hash_id. Daftarkan ulang sapi ini."
        )

    if not barn:
        raise HTTPException(
            status_code=400,
            detail="Sapi belum memiliki lokasi kandang (belum di-accept oleh pengurus)."
        )

    # Ambil Telegram ID PIC berdasarkan kandang (barn)
    pic_id = BARN_TELEGRAM_IDS.get(barn.upper())
    if not pic_id:
        raise HTTPException(
            status_code=400,
            detail=f"Tidak ada PIC untuk kandang '{barn}'."
        )

    # Update status sapi → WAITING_CONFIRMATION
    cursor.execute(
        "UPDATE cows SET status = ? WHERE cow_code = ?",
        ("WAITING_CONFIRMATION", cow_code)
    )
    conn.commit()

    # Kirim notifikasi ke PIC kandang
    send_sell_scan_request(pic_id, cow_code, barn.upper(), hash_id)

    return {
        "message": "Notifikasi dikirim ke PIC kandang",
        "cow_code": cow_code,
        "barn": barn.upper(),
        "pic_telegram_id": pic_id
    }


@app.post("/buy-feed")
def buy_feed():

    # Hitung total kebutuhan pakan dari kandang yang aktif
    cursor.execute(
        """
        SELECT COALESCE(SUM(feed_qty_needed), 0)
        FROM cows
        WHERE status NOT IN ('SOLD', 'REJECTED')
        """
    )
    total_qty = cursor.fetchone()[0] or 100  # fallback 100 kg jika belum ada data

    # Harga per kg (akan diganti sistem MRP nantinya)
    price_per_kg = 5000.0

    # Buat PO baru dengan kode unik
    po_code = f"PO-{int(time.time())}"

    cursor.execute(
        """
        INSERT INTO feed_orders(
            po_code,
            qty,
            price_per_kg,
            status
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            po_code,
            total_qty,
            price_per_kg,
            "PENDING"
        )
    )

    conn.commit()

    # Simpan daftar penerima notifikasi untuk keperluan mutual-exclusion
    suppliers = [ELISA_ID, RAFIF_ID]
    for tid in suppliers:
        cursor.execute(
            """
            INSERT INTO feed_order_recipients(po_code, telegram_id)
            VALUES (?, ?)
            """,
            (po_code, tid)
        )

    conn.commit()

    # Kirim notifikasi ke semua supplier
    for chat_id in suppliers:
        send_feed_order(
            chat_id,
            po_code,
            total_qty,
            price_per_kg
        )

    return {
        "message": "Feed order dikirim",
        "po_code": po_code,
        "qty_kg": total_qty,
        "price_per_kg": price_per_kg,
        "total_estimasi": total_qty * price_per_kg
    }


# =============================================================
# SPK – Surat Penjualan Sapi
# =============================================================

def _get_cow_full(cow_code: str) -> dict:
    """Helper: ambil data lengkap sapi + nama pemilik."""
    cursor.execute(
        """
        SELECT
            c.id, c.cow_code, c.owner_id, c.weight, c.status,
            c.caretaker, c.barn, c.jenis, c.umur, c.tgl_masuk,
            c.deskripsi, c.foto_path,
            m.name AS owner_name
        FROM cows c
        LEFT JOIN members m ON c.owner_id = m.id
        WHERE c.cow_code = ?
        """,
        (cow_code,)
    )
    row = cursor.fetchone()
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
        "owner_name": row[12],
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
    """
    Update detail informasi sapi (jenis, umur, tgl_masuk, deskripsi).
    Bisa dipanggil kapan saja — tidak mempengaruhi status/alur penjualan.
    """
    cursor.execute("SELECT id FROM cows WHERE cow_code = ?", (cow_code,))
    if not cursor.fetchone():
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

    if not fields:
        return {"message": "Tidak ada field yang diupdate."}

    values.append(cow_code)
    cursor.execute(f"UPDATE cows SET {', '.join(fields)} WHERE cow_code = ?", values)
    conn.commit()
    return {"message": "Detail sapi berhasil diperbarui.", "cow_code": cow_code}


@app.post("/cows/{cow_code}/foto")
async def upload_foto(cow_code: str, foto: UploadFile = File(...)):
    """
    Upload foto sapi. File disimpan di folder foto_sapi/ dengan nama {cow_code}.jpg/png.
    """
    cursor.execute("SELECT id FROM cows WHERE cow_code = ?", (cow_code,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail=f"Sapi '{cow_code}' tidak ditemukan.")

    # Validasi tipe file
    allowed = {"image/jpeg", "image/png", "image/webp"}
    if foto.content_type not in allowed:
        raise HTTPException(status_code=400, detail="Hanya file JPEG/PNG/WEBP yang diizinkan.")

    ext = foto.filename.rsplit(".", 1)[-1].lower() if "." in foto.filename else "jpg"
    save_path = os.path.join(FOTO_DIR, f"{cow_code}.{ext}")

    contents = await foto.read()
    with open(save_path, "wb") as f:
        f.write(contents)

    cursor.execute("UPDATE cows SET foto_path = ? WHERE cow_code = ?", (save_path, cow_code))
    conn.commit()

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

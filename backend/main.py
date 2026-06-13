import time
import uuid
import os
import mimetypes
import qrcode
import datetime
import threading
import sqlite3
import uvicorn
from io import BytesIO

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, FileResponse
from pydantic import BaseModel
from typing import Optional
from models import (
    get_session, Session,
    Member, Cow, FeedOrder, FeedOrderRecipient, KoperasiConfig,
    MilkFinancial,
)
from database import db_fetch_all, db_fetch_one, db_execute  # legacy helpers still used in a few places
from financials import FeedMRP, MilkMRP, WasteMRP, OperationalMRP, get_aggregate_report, get_koperasi_config

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
    try:
        session = get_session()
        result = session.query(Cow).count()
        db_healthy = result is not None
        Session.remove()
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
    session = get_session()
    members = session.query(Member).filter(Member.role != 'Penanggungjawab Ternak').all()
    result = []
    for m in members:
        cow_count = session.query(Cow).filter_by(owner_id=m.id).count()
        result.append({
            "id": m.id,
            "name": m.name,
            "nik": m.nik,
            "phone": m.phone,
            "alamat": m.alamat,
            "role": m.role or "Penitip Ternak",
            "barn": m.barn,
            "iuran_wajib": cow_count * 200000.0,
            "iuran_pokok": m.iuran_pokok or 1500000.0,
            "cow_count": cow_count,
        })
    Session.remove()
    return result


@app.get("/members/{member_id}")
def get_member_detail(member_id: int):
    """Detail Penitip Ternak — menampilkan sapi yang DIMILIKI."""
    session = get_session()
    m = session.query(Member).filter(
        Member.id == member_id, Member.role != 'Penanggungjawab Ternak'
    ).first()
    if not m:
        Session.remove()
        raise HTTPException(status_code=404, detail="Penitip tidak ditemukan.")

    cows = session.query(Cow).filter_by(owner_id=member_id).all()
    cow_list = [{
        "id": c.id, "cow_code": c.cow_code, "weight": c.weight, "status": c.status,
        "barn": c.barn, "jenis": c.jenis,
        "lactate_status": c.lactate_status or "Kering",
        "litre_milked_today": c.litre_milked_today or 0.0
    } for c in cows]

    member_data = {
        "id": m.id, "name": m.name, "nik": m.nik, "phone": m.phone,
        "alamat": m.alamat, "role": m.role or "Penitip Ternak", "barn": m.barn,
        "iuran_wajib": len(cow_list) * 200000.0,
        "iuran_pokok": m.iuran_pokok or 1500000.0,
        "cows": cow_list,
    }
    Session.remove()
    return member_data


@app.get("/penanggungjawab")
def get_penanggungjawab():
    """Semua Penanggungjawab Ternak beserta jumlah sapi di kandangnya."""
    session = get_session()
    pjs = session.query(Member).filter_by(role='Penanggungjawab Ternak').all()
    result = []
    for p in pjs:
        cow_count = session.query(Cow).filter_by(barn=p.barn).count() if p.barn else 0
        result.append({
            "id": p.id, "name": p.name, "nik": p.nik, "phone": p.phone,
            "alamat": p.alamat, "role": p.role, "barn": p.barn,
            "cow_count": cow_count,
        })
    Session.remove()
    return result


@app.get("/penanggungjawab/{pj_id}")
def get_penanggungjawab_detail(pj_id: int):
    """Detail Penanggungjawab Ternak — menampilkan sapi yang ADA DI KANDANGNYA."""
    session = get_session()
    p = session.query(Member).filter(
        Member.id == pj_id, Member.role == 'Penanggungjawab Ternak'
    ).first()
    if not p:
        Session.remove()
        raise HTTPException(status_code=404, detail="Penanggungjawab tidak ditemukan.")

    pj_data = {
        "id": p.id, "name": p.name, "nik": p.nik, "phone": p.phone,
        "alamat": p.alamat, "role": p.role, "barn": p.barn, "cows": []
    }

    if p.barn:
        cows = session.query(Cow).filter_by(barn=p.barn).order_by(Cow.cow_code).all()
        for c in cows:
            owner_name = c.owner.name if c.owner else "—"
            pj_data["cows"].append({
                "id": c.id, "cow_code": c.cow_code, "weight": c.weight,
                "status": c.status, "jenis": c.jenis,
                "lactate_status": c.lactate_status or "Kering",
                "litre_milked_today": c.litre_milked_today or 0.0,
                "owner_name": owner_name,
            })
    Session.remove()
    return pj_data


@app.post("/members")
def add_member(data: MemberRequest):
    try:
        session = get_session()
        m = Member(name=data.name, nik=data.nik, phone=data.phone, alamat=data.alamat, role=data.role)
        session.add(m)
        session.commit()
        member_id = m.id
        Session.remove()
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
        session = get_session()
        cow = Cow(
            cow_code=data.cow_id, status="LOOKING_FOR_CARETAKER", hash_id=hash_id,
            owner_id=data.owner_id, weight=data.weight, umur=data.umur,
            jenis=data.jenis, tgl_masuk=data.tgl_masuk, lactate_status=data.lactate_status,
        )
        session.add(cow)
        session.commit()
        Session.remove()
    except Exception as e:
        if "UNIQUE" in str(e).upper():
            raise HTTPException(status_code=400, detail=f"Sapi dengan ID '{data.cow_id}' sudah ada.")
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
        session = get_session()
        cow_obj = session.query(Cow).filter_by(cow_code=cow_code).first()
        Session.remove()
        if not cow_obj:
            raise HTTPException(status_code=404, detail="Sapi tidak ditemukan")
        hash_id = cow_obj.hash_id
        qr_url = f"https://t.me/{BOT_USERNAME}?start=CONFIRM_{cow_code}_{hash_id}"
        qr_img = qrcode.make(qr_url)
        qr_img.save(qr_path)
    return FileResponse(qr_path, media_type="image/png")


@app.get("/cows")
def get_cows():
    session = get_session()
    cows = session.query(Cow).all()
    result = []
    for c in cows:
        owner_name = c.owner.name if c.owner else None
        result.append({
            "id": c.id, "cow_code": c.cow_code, "owner_id": c.owner_id,
            "weight": c.weight, "status": c.status, "caretaker": c.caretaker,
            "feed_qty_needed": c.feed_qty_needed, "barn": c.barn,
            "hash_id": c.hash_id, "jenis": c.jenis, "owner_name": owner_name,
            "lactate_status": c.lactate_status or "Kering",
            "litre_milked_today": c.litre_milked_today or 0.0,
        })
    Session.remove()
    return result


@app.get("/cows/{cow_code}/foto")
@app.head("/cows/{cow_code}/foto")
def get_foto(cow_code: str):
    """
    Serve foto sapi dari filesystem. Mendukung GET dan HEAD request.
    """
    session = get_session()
    cow_obj = session.query(Cow).filter_by(cow_code=cow_code).first()
    if not cow_obj:
        Session.remove()
        raise HTTPException(status_code=404, detail=f"Sapi '{cow_code}' tidak ditemukan.")

    foto_path = cow_obj.foto_path
    Session.remove()
    if not foto_path or not os.path.isfile(foto_path):
        raise HTTPException(status_code=404, detail="Foto belum tersedia.")

    mime, _ = mimetypes.guess_type(foto_path)
    return FileResponse(foto_path, media_type=mime or "image/jpeg")


@app.post("/sell-cow")
def sell_cow(data: SellCowRequest):
    session = get_session()
    cow_obj = session.query(Cow).filter_by(cow_code=data.cow_code).first()
    if not cow_obj:
        Session.remove()
        raise HTTPException(status_code=404, detail=f"Sapi '{data.cow_code}' tidak ditemukan.")

    blocked_statuses = ("WAITING_CONFIRMATION", "SOLD")
    if cow_obj.status in blocked_statuses:
        Session.remove()
        raise HTTPException(status_code=400, detail=f"Sapi sudah dalam status '{cow_obj.status}', tidak bisa diproses ulang.")

    if not cow_obj.hash_id:
        Session.remove()
        raise HTTPException(status_code=400, detail="Sapi tidak memiliki hash_id. Daftarkan ulang sapi ini.")

    if not cow_obj.barn:
        Session.remove()
        raise HTTPException(status_code=400, detail="Sapi belum memiliki lokasi kandang (belum di-accept oleh pengurus).")

    pic_id = BARN_TELEGRAM_IDS.get(cow_obj.barn.upper())
    if not pic_id:
        Session.remove()
        raise HTTPException(status_code=400, detail=f"Tidak ada PIC untuk kandang '{cow_obj.barn}'.")

    cow_obj.status = "WAITING_CONFIRMATION"
    session.commit()
    Session.remove()
    send_sell_scan_request(pic_id, data.cow_code, cow_obj.barn.upper(), cow_obj.hash_id)

    return {"message": "Notifikasi dikirim ke PIC kandang", "cow_code": data.cow_code, "barn": cow_obj.barn.upper(), "pic_telegram_id": pic_id}


@app.post("/buy-feed")
def buy_feed():
    session = get_session()
    from sqlalchemy import func as sa_func
    total_qty_row = session.query(sa_func.coalesce(sa_func.sum(Cow.feed_qty_needed), 0)).filter(
        ~Cow.status.in_(['SOLD', 'REJECTED'])
    ).scalar()
    total_qty = total_qty_row or 100
    price_per_kg = 5000.0
    po_code = f"PO-{int(time.time())}"

    fo = FeedOrder(po_code=po_code, qty=total_qty, price_per_kg=price_per_kg, status="PENDING")
    session.add(fo)

    suppliers = [ELISA_ID, RAFIF_ID]
    for tid in suppliers:
        session.add(FeedOrderRecipient(po_code=po_code, telegram_id=tid))
    session.commit()
    Session.remove()

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
    """Ambil semua feed orders (PO pakan) untuk ditampilkan di halaman transaksi keuangan."""
    session = get_session()
    orders = session.query(FeedOrder).order_by(FeedOrder.id.desc()).all()
    result = [o.to_dict() for o in orders]
    Session.remove()
    return result


# =============================================================
# MILK PRODUCTION & FINANCIALS
# =============================================================

@app.get("/milk/summary")
def get_milk_summary():
    session = get_session()
    cows = session.query(Cow).filter(
        (Cow.lactate_status == 'Laktasi') | (Cow.litre_milked_today > 0)
    ).order_by(Cow.cow_code).all()
    total_today = sum(c.litre_milked_today or 0.0 for c in cows)

    cow_details = [{
        "id": c.id, "cow_code": c.cow_code,
        "lactate_status": c.lactate_status or "Kering",
        "litre_milked_today": c.litre_milked_today or 0.0,
    } for c in cows]

    past_logs = session.query(MilkFinancial).order_by(MilkFinancial.date.desc()).limit(30).all()

    total_week = total_today
    total_month = total_today
    for row in past_logs[:6]:
        total_week += row.total_liters or 0.0
    for row in past_logs[:29]:
        total_month += row.total_liters or 0.0

    latest_price = 6500.0
    if past_logs:
        latest = session.query(MilkFinancial).order_by(MilkFinancial.date.desc()).first()
        if latest and latest.price_per_liter:
            latest_price = latest.price_per_liter

    Session.remove()
    estimated_revenue_month = total_month * latest_price

    return {
        "total_today": round(total_today, 1),
        "total_week": round(total_week, 1),
        "total_month": round(total_month, 1),
        "latest_price": latest_price,
        "estimated_revenue_month": round(estimated_revenue_month, 1),
        "cows": cow_details,
        "history": [{"date": r.date, "total_liters": r.total_liters} for r in past_logs[::-1]],
    }

@app.post("/milk/financials")
def save_milk_financials(data: dict):
    try:
        session = get_session()
        existing = session.query(MilkFinancial).filter_by(date=data.get("date")).first()
        if existing:
            existing.total_liters = data.get("total_liters", 0)
            existing.price_per_liter = data.get("price_per_liter", 0)
            existing.estimated_revenue = data.get("estimated_revenue", 0)
        else:
            session.add(MilkFinancial(
                date=data.get("date"),
                total_liters=data.get("total_liters", 0),
                price_per_liter=data.get("price_per_liter", 0),
                estimated_revenue=data.get("estimated_revenue", 0),
            ))
        session.commit()
        Session.remove()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================
# SPK – Surat Penjualan Sapi
# =============================================================

def _get_cow_full(cow_code: str) -> dict:
    """Helper: ambil data lengkap sapi + nama pemilik."""
    session = get_session()
    c = session.query(Cow).filter_by(cow_code=cow_code).first()
    if not c:
        Session.remove()
        raise HTTPException(status_code=404, detail=f"Sapi '{cow_code}' tidak ditemukan.")
    owner_name = c.owner.name if c.owner else None
    result = {
        "id": c.id, "cow_code": c.cow_code, "owner_id": c.owner_id,
        "weight": c.weight, "status": c.status, "caretaker": c.caretaker,
        "barn": c.barn, "jenis": c.jenis, "umur": c.umur, "tgl_masuk": c.tgl_masuk,
        "deskripsi": c.deskripsi, "foto_path": c.foto_path,
        "lactate_status": c.lactate_status or "Kering",
        "litre_milked_today": c.litre_milked_today or 0.0,
        "owner_name": owner_name,
    }
    Session.remove()
    return result


@app.get("/cows/{cow_code}/spk")
def preview_spk(cow_code: str):
    """
    Preview data SPK sapi dalam format JSON.
    Digunakan oleh admin koperasi untuk menampilkan detail sebelum download PDF.
    """
    return _get_cow_full(cow_code)


@app.put("/cows/{cow_code}")
def update_cow_detail(cow_code: str, data: UpdateCowDetail):
    session = get_session()
    cow_obj = session.query(Cow).filter_by(cow_code=cow_code).first()
    if not cow_obj:
        Session.remove()
        raise HTTPException(status_code=404, detail=f"Sapi '{cow_code}' tidak ditemukan.")

    updated = False
    if data.jenis is not None: cow_obj.jenis = data.jenis; updated = True
    if data.umur is not None: cow_obj.umur = data.umur; updated = True
    if data.tgl_masuk is not None: cow_obj.tgl_masuk = data.tgl_masuk; updated = True
    if data.deskripsi is not None: cow_obj.deskripsi = data.deskripsi; updated = True
    if data.lactate_status is not None: cow_obj.lactate_status = data.lactate_status; updated = True
    if data.litre_milked_today is not None: cow_obj.litre_milked_today = data.litre_milked_today; updated = True
    if data.weight is not None: cow_obj.weight = data.weight; updated = True

    if not updated:
        Session.remove()
        return {"message": "Tidak ada data yang diperbarui"}

    session.commit()
    Session.remove()
    return {"message": f"Detail sapi '{cow_code}' diperbarui"}


@app.delete("/cows/{cow_code}")
def delete_cow(cow_code: str):
    session = get_session()
    cow_obj = session.query(Cow).filter_by(cow_code=cow_code).first()
    if not cow_obj:
        Session.remove()
        raise HTTPException(status_code=404, detail=f"Sapi '{cow_code}' tidak ditemukan.")

    session.delete(cow_obj)
    session.commit()
    Session.remove()
    return {"message": f"Sapi '{cow_code}' berhasil dihapus", "cow_code": cow_code}


@app.post("/cows/{cow_code}/foto")
async def upload_foto(cow_code: str, foto: UploadFile = File(...)):
    session = get_session()
    cow_obj = session.query(Cow).filter_by(cow_code=cow_code).first()
    if not cow_obj:
        Session.remove()
        raise HTTPException(status_code=404, detail=f"Sapi '{cow_code}' tidak ditemukan.")

    allowed = {"image/jpeg", "image/png", "image/webp"}
    if foto.content_type not in allowed:
        Session.remove()
        raise HTTPException(status_code=400, detail="Hanya file JPEG/PNG/WEBP yang diizinkan.")

    ext = foto.filename.rsplit(".", 1)[-1].lower() if "." in foto.filename else "jpg"
    save_path = os.path.join(FOTO_DIR, f"{cow_code}.{ext}")

    contents = await foto.read()
    with open(save_path, "wb") as f:
        f.write(contents)

    cow_obj.foto_path = save_path
    session.commit()
    Session.remove()
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


@app.get("/api/financials/feed")
def get_feed_financials():
    return FeedMRP.get_feed_report()

@app.get("/api/financials/milk")
def get_milk_financials():
    return MilkMRP.get_milk_report()

@app.get("/api/financials/waste")
def get_waste_financials():
    return WasteMRP.get_waste_report()

@app.get("/api/financials/operational")
def get_operational_financials():
    return OperationalMRP.get_operational_report()

@app.get("/api/financials/report")
def get_financial_report(period: str = "all"):
    return get_aggregate_report(period)

@app.get("/reports/{report_type}/pdf")
def download_report_pdf(report_type: str, period: str = "all"):
    from report_generator import generate_report_pdf
    
    if report_type not in ["pakan", "susu", "keuangan", "ternak"]:
        raise HTTPException(status_code=400, detail="Tipe laporan tidak valid")
        
    if report_type == "ternak":
        session = get_session()
        cows_db = session.query(Cow).all()
        report_data = {
            "cows": [{"code": c.cow_code, "weight": c.weight, "status": c.status, "barn": c.barn, "jenis": c.jenis, "umur": c.umur, "tgl_masuk": c.tgl_masuk} for c in cows_db]
        }
        Session.remove()
    else:
        report_data = get_aggregate_report(period)
        
    pdf_bytes = generate_report_pdf(report_type, period, report_data)
    filename = f"Laporan_{report_type.capitalize()}_{period}.pdf"
    
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(pdf_bytes)),
        }
    )

@app.post("/api/financials/waste/collect")
def collect_waste_daily():
    WasteMRP.collect_daily_waste()
    return {"status": "success", "message": "Daily waste collected."}

@app.get("/api/financials/feed")
def get_feed_financials():
    """Feed report data for pakan page charts and metrics."""
    return FeedMRP.get_feed_report()

@app.get("/api/financials/waste")
def get_waste_financials():
    """Waste/fertilizer report data for limbah page."""
    return WasteMRP.get_waste_report()

@app.get("/api/financials/report")
def get_financial_report(period: str = "30"):
    """Aggregate financial report for laporan page."""
    return get_aggregate_report(period)

@app.get("/api/config")
def get_config():
    """Get all koperasi configuration values."""
    session = get_session()
    rows = session.query(KoperasiConfig).all()
    result = [{"key": r.key, "value": r.value, "label": r.label} for r in rows]
    Session.remove()
    return result

@app.put("/api/config")
async def update_config(updates: dict):
    """Update one or more koperasi config values."""
    session = get_session()
    valid_keys = [r.key for r in session.query(KoperasiConfig).all()]
    updated = []
    for key, value in updates.items():
        if key in valid_keys:
            cfg = session.query(KoperasiConfig).filter_by(key=key).first()
            if cfg:
                cfg.value = float(value)
                updated.append(key)
    if not updated:
        Session.remove()
        raise HTTPException(status_code=400, detail="No valid config keys provided")
    session.commit()
    Session.remove()
    return {"status": "success", "updated": updated}

@app.on_event("startup")
async def startup_event():
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

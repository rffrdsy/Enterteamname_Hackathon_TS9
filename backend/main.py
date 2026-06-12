from fastapi import FastAPI
from pydantic import BaseModel
from database import conn, cursor

from telegram_bot import (
    start_bot,
    send_new_cow,
    send_prepare_sale,
    send_feed_order
)

from config import (
    ABYASA_ID,
    AXEL_ID,
    ELISA_ID,
    RAFIF_ID
)

import threading
import uvicorn

app = FastAPI()


class CowRequest(BaseModel):
    cow_id: str
    owner: str


@app.get("/")
def home():
    return {"status": "running"}


@app.post("/new-cow")
def new_cow(data: CowRequest):

    cursor.execute(
        """
        INSERT INTO cows(
            cow_code,
            status
        )
        VALUES (?, ?)
        """,
        (
            data.cow_id,
            "LOOKING_FOR_CARETAKER"
        )
    )

    conn.commit()

    send_new_cow(
    data.cow_id,
    data.owner
)

    return {
        "message": "cow saved and notification sent"
    }

@app.get("/cows")
def get_cows():

    cursor.execute(
        "SELECT * FROM cows"
    )

    rows = cursor.fetchall()

    return rows


@app.post("/sell-cow")
def sell_cow():

    for chat_id in [AXEL_ID, ABYASA_ID]:
        send_prepare_sale(
            chat_id,
            "SPR-001"
        )

    return {
        "message": "sale notification sent"
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
    import time
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
        "message": "feed order sent",
        "po_code": po_code,
        "qty_kg": total_qty,
        "price_per_kg": price_per_kg,
        "total_estimasi": total_qty * price_per_kg
    }


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


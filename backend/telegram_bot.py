import telebot

from config import (
    API_TOKEN,
    ABYASA_ID,
    AXEL_ID,
    ELISA_ID,
    RAFIF_ID,
    BOT_USERNAME,
    BARN_TELEGRAM_IDS
)

SUPPLIER_NAMES = {
    ELISA_ID: "ELISA",
    RAFIF_ID: "RAFIF",
}
from database import conn, cursor

from telebot.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton
)

bot = telebot.TeleBot(API_TOKEN)


# =========================
# COMMANDS
# =========================

@bot.message_handler(commands=['start'])
def start(message):

    print("CHAT ID:", message.chat.id)

    text = message.text.strip()
    parts = text.split(" ", 1)

    # Handle deep link payload: /start CONFIRM_{cow_code}_{hash_id}
    if len(parts) > 1:
        payload = parts[1].strip()

        if payload.startswith("CONFIRM_"):
            # Format: CONFIRM_{cow_code}_{hash_id}
            # hash_id selalu 8 karakter di akhir, dipisah underscore terakhir
            inner = payload[len("CONFIRM_"):]
            segments = inner.rsplit("_", 1)

            if len(segments) == 2:
                cow_code, hash_id = segments
                _handle_confirm_sell(message, cow_code, hash_id)
                return

    bot.send_message(
        message.chat.id,
        f"Halo {message.from_user.first_name}"
    )


def _handle_confirm_sell(message, cow_code, hash_id):
    """Validasi QR scan: cocokkan cow_code + hash_id lalu tampilkan tombol konfirmasi."""

    cursor.execute(
        """
        SELECT cow_code, status, hash_id, barn
        FROM cows
        WHERE cow_code = ?
        """,
        (cow_code,)
    )
    row = cursor.fetchone()

    if not row:
        bot.send_message(message.chat.id, "❌ QR Code tidak valid. Sapi tidak ditemukan.")
        return

    db_cow_code, status, db_hash_id, barn = row

    # Validasi hash
    if hash_id != db_hash_id:
        bot.send_message(message.chat.id, "❌ QR Code tidak valid. Hash tidak cocok.")
        return

    # Validasi otorisasi: hanya PIC kandang yang boleh konfirmasi
    authorized_id = BARN_TELEGRAM_IDS.get((barn or "").upper())
    if message.from_user.id != authorized_id:
        bot.send_message(
            message.chat.id,
            f"🚫 Akses ditolak. Hanya penanggungjawab ternak {barn or '?'} yang bisa mengkonfirmasi sapi ini."
        )
        return

    # Validasi status
    if status != "WAITING_CONFIRMATION":
        status_msg = {
            "SOLD": "ℹ️ Sapi ini sudah terjual.",
        }.get(status, f"⚠️ Sapi ini tidak sedang dalam proses konfirmasi (status: {status}).")
        bot.send_message(message.chat.id, status_msg)
        return

    # Tampilkan tombol konfirmasi
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton(
            "✅ Konfirmasi Siap Jual",
            callback_data=f"confirmsell_{cow_code}"
        )
    )

    msg = bot.send_message(
        message.chat.id,
        f"""
🔍 VERIFIKASI SAPI

Kode    : {cow_code}
Kandang : {barn or '-'}
Status  : WAITING CONFIRMATION

Tekan tombol di bawah untuk konfirmasi sapi siap dijual.
""",
        reply_markup=markup
    )

    # Simpan referensi pesan agar tombol bisa dihapus setelah dikonfirmasi
    cursor.execute(
        "INSERT INTO message_refs(ref_type, ref_id, chat_id, message_id) VALUES (?, ?, ?, ?)",
        ("confirmsell", cow_code, msg.chat.id, msg.message_id)
    )
    conn.commit()


# =========================
# DAILY KANDANG LOG (/lapor)
# =========================

from datetime import datetime

@bot.message_handler(commands=['lapor'])
def lapor_kandang(message):
    telegram_id = message.from_user.id
    
    # Cari tahu ini kandang apa
    barn = None
    for b, t_id in BARN_TELEGRAM_IDS.items():
        if t_id == telegram_id:
            barn = b
            break
            
    if not barn:
        bot.send_message(message.chat.id, "🚫 Anda tidak terdaftar sebagai penanggungjawab kandang.")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    
    # Cek status pakan & susu hari ini
    cursor.execute("SELECT id FROM daily_kandang_logs WHERE date = ? AND barn = ? AND type = 'PAKAN'", (today, barn))
    pakan_log = cursor.fetchone()
    
    cursor.execute("SELECT id FROM daily_kandang_logs WHERE date = ? AND barn = ? AND type = 'SUSU'", (today, barn))
    susu_log = cursor.fetchone()

    markup = InlineKeyboardMarkup(row_width=1)
    
    if pakan_log:
        markup.add(InlineKeyboardButton("↩️ Batal (Undo) Pakan", callback_data=f"undo_log_{pakan_log[0]}"))
    else:
        markup.add(InlineKeyboardButton("🌾 Selesai Beri Pakan", callback_data=f"lapor_pakan_{barn}"))
        
    if susu_log:
        markup.add(InlineKeyboardButton("↩️ Batal (Undo) Susu", callback_data=f"undo_log_{susu_log[0]}"))
    else:
        markup.add(InlineKeyboardButton("🥛 Selesai Perah Susu", callback_data=f"lapor_susu_{barn}"))
        
    markup.add(InlineKeyboardButton("🩺 Lapor Sapi Sakit/Mati", callback_data=f"lapor_sakit_{barn}"))
    
    bot.send_message(
        message.chat.id,
        f"📝 *Laporan Harian Kandang {barn}*\nTanggal: {today}\n\nPilih laporan yang ingin disubmit:",
        parse_mode="Markdown",
        reply_markup=markup
    )

# =========================
# BOT START
# =========================

def resend_waiting_confirmations():
    """Saat server nyala, kirim ulang notifikasi untuk sapi yang masih WAITING_CONFIRMATION."""
    cursor.execute(
        """
        SELECT cow_code, barn, hash_id
        FROM cows
        WHERE status = 'WAITING_CONFIRMATION'
        """
    )
    rows = cursor.fetchall()
    if not rows:
        return
    print(f"[STARTUP] {len(rows)} sapi masih WAITING_CONFIRMATION, mengirim ulang notifikasi...")
    for cow_code, barn, hash_id in rows:
        if not barn or not hash_id:
            continue
        pic_id = BARN_TELEGRAM_IDS.get(barn.upper())
        if pic_id:
            send_sell_scan_request(pic_id, cow_code, barn.upper(), hash_id)
            print(f"[STARTUP] Notifikasi ulang dikirim ke PIC kandang {barn} untuk sapi {cow_code}")


def start_bot():

    print("Bot Running...")
    resend_waiting_confirmations()
    bot.infinity_polling()


# =========================
# HELPER: HAPUS TOMBOL
# =========================

def clear_buttons(ref_type, ref_id):
    """Edit semua pesan terkait ref_id agar tombolnya hilang."""
    cursor.execute(
        """
        SELECT chat_id, message_id
        FROM message_refs
        WHERE ref_type = ? AND ref_id = ?
        """,
        (ref_type, ref_id)
    )
    rows = cursor.fetchall()
    for (chat_id, message_id) in rows:
        try:
            bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=InlineKeyboardMarkup()
            )
        except Exception as e:
            print(f"Gagal hapus tombol chat_id={chat_id} msg_id={message_id}: {e}")
    cursor.execute(
        "DELETE FROM message_refs WHERE ref_type = ? AND ref_id = ?",
        (ref_type, ref_id)
    )
    conn.commit()


# =========================
# SEND NEW COW
# =========================

def send_new_cow(cow_id, owner):

    markup = InlineKeyboardMarkup()

    btn_accept = InlineKeyboardButton(
        "✅ Terima",
        callback_data=f"accept_{cow_id}"
    )

    btn_reject = InlineKeyboardButton(
        "❌ Penuh",
        callback_data=f"reject_{cow_id}"
    )

    markup.add(btn_accept)
    markup.add(btn_reject)

    for target in [ABYASA_ID, AXEL_ID]:
        try:
            msg = bot.send_message(
                target,
                f"""
🐄 PERMINTAAN KANDANG

ID: {cow_id}
Pemilik: {owner}

Apakah masih ada kapasitas?
""",
                reply_markup=markup
            )
            # Simpan referensi pesan untuk hapus tombol nanti
            cursor.execute(
                "INSERT INTO message_refs(ref_type, ref_id, chat_id, message_id) VALUES (?, ?, ?, ?)",
                ("cow_accept", cow_id, msg.chat.id, msg.message_id)
            )
            conn.commit()
        except Exception as e:
            print(f"Gagal mengirim permintaan kandang ke {target}: {e}")


# =========================
# SEND SELL SCAN REQUEST
# =========================

def send_sell_scan_request(chat_id, cow_code, barn, hash_id):
    """Kirim notifikasi ke PIC kandang untuk scan QR Code eartag sapi."""

    deep_link = f"https://t.me/{BOT_USERNAME}?start=CONFIRM_{cow_code}_{hash_id}"
    
    # Cetak ke terminal untuk keperluan development (generate QR code, dsb)
    print("=" * 50)
    print(f"🔗 [QR URL DEV] Sapi {cow_code}:")
    print(deep_link)
    print("=" * 50)

    try:
        bot.send_message(
            chat_id,
            f"""
🔍 PERMINTAAN VERIFIKASI JUAL

Sapi    : {cow_code}
Kandang : {barn}

Silakan scan QR Code pada eartag sapi untuk konfirmasi penjualan.
"""
        )
    except Exception as e:
        print(f"Gagal mengirim notifikasi scan QR ke {chat_id}: {e}")


# =========================
# FEED ORDER
# =========================

def send_feed_order(chat_id, po_id, qty, price_per_kg):

    total_price = qty * price_per_kg

    markup = InlineKeyboardMarkup()

    btn_accept = InlineKeyboardButton(
        "✅ Setuju",
        callback_data=f"confirmpo_{po_id}"
    )

    btn_reject = InlineKeyboardButton(
        "❌ Tolak",
        callback_data=f"rejectpo_{po_id}"
    )

    markup.add(btn_accept)
    markup.add(btn_reject)

    try:
        msg = bot.send_message(
            chat_id,
            f"""
📦 PURCHASE ORDER

PO ID        : {po_id}
Volume       : {qty:,.0f} kg
Harga/kg     : Rp {price_per_kg:,.0f}
Total Estimasi: Rp {total_price:,.0f}

Mohon konfirmasi pesanan.
""",
            reply_markup=markup
        )
        # Simpan referensi pesan untuk hapus tombol nanti
        cursor.execute(
            "INSERT INTO message_refs(ref_type, ref_id, chat_id, message_id) VALUES (?, ?, ?, ?)",
            ("feed_order", po_id, msg.chat.id, msg.message_id)
        )
        conn.commit()
    except Exception as e:
        print(f"Gagal mengirim feed order ke {chat_id}: {e}")


# =========================
# CALLBACK HANDLER
# =========================

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):

    # TERIMA SAPI
    if call.data.startswith("accept_"):

        cow_id = call.data.replace("accept_", "")

        cursor.execute(
            """
            SELECT caretaker
            FROM cows
            WHERE cow_code = ?
            """,
            (cow_id,)
        )
        row = cursor.fetchone()

        if row and row[0]:
            bot.answer_callback_query(call.id)
            bot.send_message(
                call.message.chat.id,
                f"❌ {cow_id} sudah diterima kandang lain."
            )
            return

        telegram_id = call.from_user.id

        # Tentukan barn dari telegram_id
        barn = None
        for b, t_id in BARN_TELEGRAM_IDS.items():
            if t_id == telegram_id:
                barn = b
                break

        if telegram_id == ABYASA_ID:
            caretaker = "ABYASA"
        elif telegram_id == AXEL_ID:
            caretaker = "AXEL"
        else:
            caretaker = "UNKNOWN"

        if not barn:
            barn = "UNKNOWN"

        cursor.execute(
            """
            UPDATE cows
            SET caretaker = ?,
                barn = ?,
                status = ?
            WHERE cow_code = ?
            """,
            (
                caretaker,
                barn,
                "AVAILABLE",
                cow_id
            )
        )

        conn.commit()

        bot.answer_callback_query(call.id)

        bot.send_message(
            call.message.chat.id,
            f"""
✅ {cow_id}

Dialokasikan ke:
Kandang {barn} ({caretaker})

Status:
AVAILABLE
"""
        )

        print(f"{cow_id} -> {caretaker}")

        # Hapus tombol dari semua pesan terkait cow ini
        clear_buttons("cow_accept", cow_id)

        # Notifikasi pihak lain bahwa kandang sudah diambil
        for other_id in [AXEL_ID, ABYASA_ID]:
            if other_id != telegram_id:
                try:
                    bot.send_message(
                        other_id,
                        f"ℹ️ {cow_id} sudah diterima oleh {caretaker}.\n\nAnda tidak perlu melakukan tindakan apapun."
                    )
                except Exception as e:
                    print(f"Gagal kirim notifikasi penerimaan ke {other_id}: {e}")


    # TOLAK / PENUH
    elif call.data.startswith("reject_"):

        cow_id = call.data.replace("reject_", "")

        cursor.execute(
            """
            UPDATE cows
            SET status = ?
            WHERE cow_code = ?
            """,
            (
                "REJECTED",
                cow_id
            )
        )

        print("Rows Updated:", cursor.rowcount)

        conn.commit()

        bot.answer_callback_query(call.id)

        bot.send_message(
            call.message.chat.id,
            f"❌ {cow_id} ditolak karena kandang penuh."
        )

        print(f"{cow_id} REJECTED")


    # KONFIRMASI SIAP JUAL (via QR scan)
    elif call.data.startswith("confirmsell_"):

        cow_code = call.data.replace("confirmsell_", "")

        # Mutual exclusion: cek status terkini
        cursor.execute(
            "SELECT status FROM cows WHERE cow_code = ?",
            (cow_code,)
        )
        row = cursor.fetchone()

        if not row:
            bot.answer_callback_query(call.id)
            bot.send_message(call.message.chat.id, "❌ Sapi tidak ditemukan.")
            return

        current_status = row[0]

        if current_status == "SOLD":
            bot.answer_callback_query(call.id)
            bot.send_message(
                call.message.chat.id,
                f"ℹ️ {cow_code} sudah terjual."
            )
            return

        if current_status != "WAITING_CONFIRMATION":
            bot.answer_callback_query(call.id)
            bot.send_message(
                call.message.chat.id,
                f"⚠️ {cow_code} tidak sedang dalam proses konfirmasi (status: {current_status})."
            )
            return

        # Update status → SOLD
        cursor.execute(
            "UPDATE cows SET status = ? WHERE cow_code = ?",
            ("SOLD", cow_code)
        )
        conn.commit()

        bot.answer_callback_query(call.id)

        bot.send_message(
            call.message.chat.id,
            f"""
✅ Penjualan berhasil dikonfirmasi!

Sapi   : {cow_code}
Status : SOLD

Sapi telah resmi terjual.
"""
        )

        print(f"{cow_code} SOLD (confirmed via QR)")

        # Hapus tombol konfirmasi
        clear_buttons("confirmsell", cow_code)


    # PO DISETUJUI
    elif call.data.startswith("confirmpo_"):

        po_id = call.data.replace("confirmpo_", "")

        # Cek apakah PO sudah diambil supplier lain
        cursor.execute(
            """
            SELECT status, supplier
            FROM feed_orders
            WHERE po_code = ?
            """,
            (po_id,)
        )
        row = cursor.fetchone()

        if row and row[0] == "CONFIRMED":
            bot.answer_callback_query(call.id)
            bot.send_message(
                call.message.chat.id,
                f"❌ {po_id} sudah dikonfirmasi oleh {row[1]}."
            )
            return

        telegram_id = call.from_user.id
        supplier_name = SUPPLIER_NAMES.get(telegram_id, "UNKNOWN")

        cursor.execute(
            """
            UPDATE feed_orders
            SET status = ?,
                supplier = ?
            WHERE po_code = ?
            """,
            (
                "CONFIRMED",
                supplier_name,
                po_id
            )
        )

        conn.commit()

        bot.answer_callback_query(call.id)

        bot.send_message(
            call.message.chat.id,
            f"✅ {po_id} dikonfirmasi.\n\nSupplier: {supplier_name}\nStatus: CONFIRMED"
        )

        print(f"{po_id} CONFIRMED by {supplier_name}")

        # Hapus tombol dari semua pesan PO terkait
        clear_buttons("feed_order", po_id)

        # Notify supplier lain bahwa PO sudah diambil
        cursor.execute(
            """
            SELECT telegram_id
            FROM feed_order_recipients
            WHERE po_code = ?
            AND telegram_id != ?
            """,
            (po_id, telegram_id)
        )
        other_recipients = cursor.fetchall()

        for (other_id,) in other_recipients:
            try:
                bot.send_message(
                    other_id,
                    f"ℹ️ {po_id} sudah dikonfirmasi oleh {supplier_name}.\n\nAnda tidak perlu mengambil pesanan ini."
                )
            except Exception as e:
                print(f"Gagal kirim notifikasi ke {other_id}: {e}")


    # PO DITOLAK
    elif call.data.startswith("rejectpo_"):

        po_id = call.data.replace("rejectpo_", "")

        cursor.execute(
            """
            UPDATE feed_orders
            SET status = ?
            WHERE po_code = ?
            """,
            (
                "REJECTED",
                po_id
            )
        )

        conn.commit()

        bot.answer_callback_query(call.id)

        bot.send_message(
            call.message.chat.id,
            f"❌ {po_id} ditolak supplier."
        )

        print(f"{po_id} REJECTED")

    # ===============================
    # LAPOR HARIAN KANDANG
    # ===============================
    elif call.data.startswith("lapor_pakan_") or call.data.startswith("lapor_susu_"):
        parts = call.data.split("_")
        lapor_type = parts[1] # pakan / susu
        barn = parts[2]
        telegram_id = call.from_user.id
        today = datetime.now().strftime("%Y-%m-%d")
        
        cursor.execute(
            "INSERT INTO daily_kandang_logs (date, barn, type, telegram_id) VALUES (?, ?, ?, ?)",
            (today, barn, lapor_type.upper(), telegram_id)
        )
        conn.commit()
        
        bot.answer_callback_query(call.id, f"Laporan {lapor_type} disimpan!")
        bot.edit_message_text(
            f"✅ *{lapor_type.capitalize()}* Selesai dicatat.\n\n_Ketik /lapor lagi untuk melihat menu lainnya atau membatalkan._",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup()
        )
        
    elif call.data.startswith("lapor_sakit_"):
        barn = call.data.replace("lapor_sakit_", "")
        
        # Ambil daftar sapi di kandang tersebut
        cursor.execute("SELECT cow_code FROM cows WHERE barn = ? AND status NOT IN ('SOLD', 'DEAD', 'REJECTED')", (barn,))
        rows = cursor.fetchall()
        
        if not rows:
            bot.answer_callback_query(call.id)
            bot.send_message(call.message.chat.id, f"Tidak ada sapi aktif di Kandang {barn}.")
            return
            
        markup = InlineKeyboardMarkup(row_width=2)
        for row in rows:
            markup.add(InlineKeyboardButton(f"Sapi {row[0]}", callback_data=f"sickselect_{row[0]}"))
            
        bot.answer_callback_query(call.id)
        bot.send_message(
            call.message.chat.id,
            "Pilih sapi yang bermasalah:",
            reply_markup=markup
        )
        
    elif call.data.startswith("sickselect_"):
        cow_code = call.data.replace("sickselect_", "")
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("🩺 Dilaporkan Sakit", callback_data=f"marksick_{cow_code}"),
            InlineKeyboardButton("☠️ Dilaporkan Mati", callback_data=f"markdead_{cow_code}")
        )
        bot.answer_callback_query(call.id)
        bot.send_message(
            call.message.chat.id,
            f"Kondisi sapi {cow_code}:",
            reply_markup=markup
        )
        
    elif call.data.startswith("marksick_"):
        cow_code = call.data.replace("marksick_", "")
        cursor.execute("UPDATE cows SET status = 'SICK' WHERE cow_code = ?", (cow_code,))
        conn.commit()
        
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("↩️ Batalkan (Undo)", callback_data=f"undo_sick_{cow_code}"))
        
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, f"✅ Status sapi {cow_code} diubah menjadi SAKIT.", reply_markup=markup)
        
    elif call.data.startswith("markdead_"):
        cow_code = call.data.replace("markdead_", "")
        cursor.execute("UPDATE cows SET status = 'DEAD' WHERE cow_code = ?", (cow_code,))
        conn.commit()
        
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("↩️ Batalkan (Undo)", callback_data=f"undo_dead_{cow_code}"))

        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, f"✅ Status sapi {cow_code} diubah menjadi MATI.", reply_markup=markup)
        
    # ===============================
    # UNDO HANDLERS
    # ===============================
    elif call.data.startswith("undo_log_"):
        log_id = call.data.replace("undo_log_", "")
        cursor.execute("DELETE FROM daily_kandang_logs WHERE id = ?", (log_id,))
        conn.commit()
        
        bot.answer_callback_query(call.id, "Laporan dibatalkan!")
        bot.edit_message_text(
            "🔄 *Laporan harian dibatalkan.*\n\n_Ketik /lapor lagi untuk melihat menu._",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup()
        )

    elif call.data.startswith("undo_sick_") or call.data.startswith("undo_dead_"):
        parts = call.data.split("_")
        cow_code = parts[2]
        
        cursor.execute("UPDATE cows SET status = 'AVAILABLE' WHERE cow_code = ?", (cow_code,))
        conn.commit()
        
        bot.answer_callback_query(call.id, "Status dibatalkan!")
        bot.edit_message_text(
            f"🔄 Status sapi {cow_code} dikembalikan menjadi Normal (*AVAILABLE*).",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="Markdown"
        )
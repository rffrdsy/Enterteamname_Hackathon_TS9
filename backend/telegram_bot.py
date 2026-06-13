# pyrefly: ignore [missing-import]
import telebot
import time

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
from models import get_session, Session, Cow, FeedOrder, FeedOrderRecipient, MessageRef, DailyKandangLog

# pyrefly: ignore [missing-import]
from telebot.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton
)

bot = telebot.TeleBot(API_TOKEN)

# Reference to main.py's BOT_STATUS — set at start_bot() call time
_bot_status_ref = None

def set_bot_status_ref(status_dict):
    """Called from main.py to inject the BOT_STATUS dict reference."""
    global _bot_status_ref
    _bot_status_ref = status_dict

def _mark_bot_activity():
    """Update BOT_STATUS timestamp on any activity."""
    if _bot_status_ref is not None:
        _bot_status_ref["connected"] = True
        _bot_status_ref["last_update_ts"] = time.time()


# =========================
# STATE DICTIONARY
# =========================
milk_reporting_state = {}

def render_main_milk_board(chat_id):
    state = milk_reporting_state.get(chat_id)
    if not state:
        return InlineKeyboardMarkup()
    markup = InlineKeyboardMarkup(row_width=1)
    for cow in state['cows']:
        liters = state['liters'][cow]
        markup.add(InlineKeyboardButton(f"🐄 {cow} : {liters} L", callback_data=f"selectmilk|{cow}"))
    markup.add(InlineKeyboardButton("✅ Selesai & Simpan", callback_data="save_milk_report"))
    return markup

def render_edit_milk_board(cow):
    markup = InlineKeyboardMarkup(row_width=3)
    markup.add(
        InlineKeyboardButton("-5", callback_data=f"adjmilk|{cow}|-5"),
        InlineKeyboardButton("-1", callback_data=f"adjmilk|{cow}|-1"),
        InlineKeyboardButton("-0.5", callback_data=f"adjmilk|{cow}|-0.5"),
        InlineKeyboardButton("+0.5", callback_data=f"adjmilk|{cow}|0.5"),
        InlineKeyboardButton("+1", callback_data=f"adjmilk|{cow}|1"),
        InlineKeyboardButton("+5", callback_data=f"adjmilk|{cow}|5")
    )
    markup.add(InlineKeyboardButton("🔙 Kembali", callback_data="back_milk_main"))
    return markup

# =========================
# COMMANDS
# =========================

@bot.message_handler(commands=['start'])
def start(message):
    _mark_bot_activity()
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

    session = get_session()
    cow = session.query(Cow).filter_by(cow_code=cow_code).first()
    row = (cow.cow_code, cow.status, cow.hash_id, cow.barn) if cow else None

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
    session.add(MessageRef(ref_type="confirmsell", ref_id=cow_code, chat_id=msg.chat.id, message_id=msg.message_id))
    session.commit()
    Session.remove()


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
    
    # Cek status pakan & susu & limbah hari ini
    session = get_session()
    pakan_obj = session.query(DailyKandangLog).filter_by(date=today, barn=barn, type='PAKAN').first()
    pakan_log = (pakan_obj.id,) if pakan_obj else None
    
    susu_obj = session.query(DailyKandangLog).filter_by(date=today, barn=barn, type='SUSU').first()
    susu_log = (susu_obj.id,) if susu_obj else None

    limbah_obj = session.query(DailyKandangLog).filter_by(date=today, barn=barn, type='LIMBAH').first()
    limbah_log = (limbah_obj.id,) if limbah_obj else None
    Session.remove()

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

    if limbah_log:
        markup.add(InlineKeyboardButton("↩️ Batal (Undo) Limbah", callback_data=f"undo_log_{limbah_log[0]}"))
    else:
        markup.add(InlineKeyboardButton("💩 Selesai Kumpul Limbah", callback_data=f"lapor_limbah_{barn}"))
    
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
    session = get_session()
    waiting_cows = session.query(Cow).filter_by(status='WAITING_CONFIRMATION').all()
    rows = [(c.cow_code, c.barn, c.hash_id) for c in waiting_cows]
    Session.remove()
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
    if _bot_status_ref is not None:
        _bot_status_ref["start_ts"] = time.time()
    resend_waiting_confirmations()

    retry_delay = 5  # seconds, will double on each 409 conflict up to 60s
    while True:
        try:
            if _bot_status_ref is not None:
                _bot_status_ref["connected"] = True
            bot.infinity_polling(timeout=30, long_polling_timeout=20)
        except Exception as e:
            err_str = str(e)
            if _bot_status_ref is not None:
                _bot_status_ref["connected"] = False
            if "409" in err_str or "Conflict" in err_str:
                print(f"[BOT] 409 Conflict — another instance may still be shutting down. Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 60)  # exponential backoff, max 60s
            else:
                print(f"[BOT] Polling error: {e}. Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
        else:
            # polling ended cleanly (no exception)
            if _bot_status_ref is not None:
                _bot_status_ref["connected"] = False
            print("[BOT] Polling stopped cleanly.")
            break


# =========================
# HELPER: HAPUS TOMBOL
# =========================

def clear_buttons(ref_type, ref_id):
    """Edit semua pesan terkait ref_id agar tombolnya hilang."""
    session = get_session()
    refs = session.query(MessageRef).filter_by(ref_type=ref_type, ref_id=ref_id).all()
    for ref in refs:
        try:
            bot.edit_message_reply_markup(
                chat_id=ref.chat_id,
                message_id=ref.message_id,
                reply_markup=InlineKeyboardMarkup()
            )
        except Exception as e:
            print(f"Gagal hapus tombol chat_id={ref.chat_id} msg_id={ref.message_id}: {e}")
    session.query(MessageRef).filter_by(ref_type=ref_type, ref_id=ref_id).delete()
    session.commit()
    Session.remove()


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
            s = get_session()
            s.add(MessageRef(ref_type="cow_accept", ref_id=cow_id, chat_id=msg.chat.id, message_id=msg.message_id))
            s.commit()
            Session.remove()
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
        s = get_session()
        s.add(MessageRef(ref_type="feed_order", ref_id=po_id, chat_id=msg.chat.id, message_id=msg.message_id))
        s.commit()
        Session.remove()
    except Exception as e:
        print(f"Gagal mengirim feed order ke {chat_id}: {e}")


# =========================
# CALLBACK HANDLER
# =========================

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    _mark_bot_activity()

    # TERIMA SAPI
    if call.data.startswith("accept_"):

        cow_id = call.data.replace("accept_", "")

        session = get_session()
        cow_obj = session.query(Cow).filter_by(cow_code=cow_id).first()

        if cow_obj and cow_obj.caretaker:
            Session.remove()
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

        if cow_obj:
            cow_obj.caretaker = caretaker
            cow_obj.barn = barn
            cow_obj.status = "AVAILABLE"
            session.commit()
        Session.remove()

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

        session = get_session()
        cow_obj = session.query(Cow).filter_by(cow_code=cow_id).first()
        if cow_obj:
            cow_obj.status = "REJECTED"
            session.commit()
            print("Rows Updated: 1")
        Session.remove()

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
        session = get_session()
        cow_obj = session.query(Cow).filter_by(cow_code=cow_code).first()

        if not cow_obj:
            Session.remove()
            bot.answer_callback_query(call.id)
            bot.send_message(call.message.chat.id, "❌ Sapi tidak ditemukan.")
            return

        current_status = cow_obj.status

        if current_status == "SOLD":
            Session.remove()
            bot.answer_callback_query(call.id)
            bot.send_message(
                call.message.chat.id,
                f"ℹ️ {cow_code} sudah terjual."
            )
            return

        if current_status != "WAITING_CONFIRMATION":
            Session.remove()
            bot.answer_callback_query(call.id)
            bot.send_message(
                call.message.chat.id,
                f"⚠️ {cow_code} tidak sedang dalam proses konfirmasi (status: {current_status})."
            )
            return

        # Update status → SOLD
        cow_obj.status = "SOLD"
        session.commit()
        Session.remove()

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
        session = get_session()
        fo = session.query(FeedOrder).filter_by(po_code=po_id).first()

        if fo and fo.status == "CONFIRMED":
            Session.remove()
            bot.answer_callback_query(call.id)
            bot.send_message(
                call.message.chat.id,
                f"❌ {po_id} sudah dikonfirmasi oleh {fo.supplier}."
            )
            return

        telegram_id = call.from_user.id
        supplier_name = SUPPLIER_NAMES.get(telegram_id, "UNKNOWN")

        if fo:
            fo.status = "CONFIRMED"
            fo.supplier = supplier_name
            session.commit()

        bot.answer_callback_query(call.id)

        bot.send_message(
            call.message.chat.id,
            f"✅ {po_id} dikonfirmasi.\n\nSupplier: {supplier_name}\nStatus: CONFIRMED"
        )

        print(f"{po_id} CONFIRMED by {supplier_name}")

        # Hapus tombol dari semua pesan PO terkait
        clear_buttons("feed_order", po_id)

        # Notify supplier lain bahwa PO sudah diambil
        other_recipients = session.query(FeedOrderRecipient).filter(
            FeedOrderRecipient.po_code == po_id,
            FeedOrderRecipient.telegram_id != telegram_id,
        ).all()
        other_recipients = [(r.telegram_id,) for r in other_recipients]
        Session.remove()

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

        session = get_session()
        fo = session.query(FeedOrder).filter_by(po_code=po_id).first()
        if fo:
            fo.status = "REJECTED"
            session.commit()
        Session.remove()

        bot.answer_callback_query(call.id)

        bot.send_message(
            call.message.chat.id,
            f"❌ {po_id} ditolak supplier."
        )

        print(f"{po_id} REJECTED")

    # ===============================
    # LAPOR HARIAN KANDANG
    # ===============================
    elif call.data.startswith("lapor_pakan_"):
        barn = call.data.replace("lapor_pakan_", "")
        telegram_id = call.from_user.id
        today = datetime.now().strftime("%Y-%m-%d")
        
        session = get_session()
        session.add(DailyKandangLog(date=today, barn=barn, type='PAKAN', telegram_id=telegram_id))
        session.commit()
        Session.remove()
        
        bot.answer_callback_query(call.id, "Laporan Pakan disimpan!")
        bot.edit_message_text(
            "✅ *Pakan* Selesai dicatat.\n\n_Ketik /lapor lagi untuk melihat menu lainnya atau membatalkan._",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup()
        )

    elif call.data.startswith("lapor_limbah_"):
        barn = call.data.replace("lapor_limbah_", "")
        telegram_id = call.from_user.id
        today = datetime.now().strftime("%Y-%m-%d")
        
        session = get_session()
        # Count active cows in this barn
        cow_count = session.query(Cow).filter(
            Cow.barn == barn,
            ~Cow.status.in_(['SOLD', 'DEAD', 'REJECTED']),
        ).count()
        waste_kg = cow_count * 10  # 10 kg per sapi per hari
        
        session.add(DailyKandangLog(date=today, barn=barn, type='LIMBAH', telegram_id=telegram_id))
        session.commit()
        Session.remove()
        
        bot.answer_callback_query(call.id, f"Limbah {waste_kg} kg dicatat!")
        bot.edit_message_text(
            f"✅ *Limbah* Kandang {barn} dicatat.\n\n"
            f"🐄 Sapi aktif: {cow_count} ekor\n"
            f"💩 Total limbah hari ini: {waste_kg} kg\n"
            f"♻️ Est. pupuk setelah fermentasi: {int(waste_kg * 0.6)} kg\n\n"
            f"_Ketik /lapor lagi untuk melihat menu lainnya atau membatalkan._",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup()
        )

    elif call.data.startswith("lapor_susu_"):
        barn = call.data.replace("lapor_susu_", "")
        
        session = get_session()
        cows_q = session.query(Cow).filter(
            Cow.barn == barn,
            ~Cow.status.in_(['SOLD', 'DEAD', 'REJECTED']),
        ).filter(
            (Cow.jenis == 'Perah') | (Cow.lactate_status == 'Laktasi')
        ).all()
        rows = [(c.cow_code,) for c in cows_q]
        Session.remove()
        
        if not rows:
            bot.answer_callback_query(call.id, "Tidak ada Sapi Perah aktif.")
            bot.send_message(call.message.chat.id, f"Tidak ada Sapi Perah aktif di Kandang {barn}.")
            return
            
        cows_list = [r[0] for r in rows]
        milk_reporting_state[call.message.chat.id] = {
            "cows": cows_list,
            "liters": {c: 0.0 for c in cows_list},
            "barn": barn
        }
        
        bot.answer_callback_query(call.id)
        bot.edit_message_text(
            f"📝 *Pencatatan Susu (Kandang {barn})*\nSilakan klik nama sapi untuk mengatur hasil susu (Liter):",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="Markdown",
            reply_markup=render_main_milk_board(call.message.chat.id)
        )

    elif call.data.startswith("selectmilk|"):
        cow = call.data.split("|", 1)[1]
        chat_id = call.message.chat.id
        state = milk_reporting_state.get(chat_id)
        if not state:
            bot.answer_callback_query(call.id, "Sesi habis, silakan mulai ulang /lapor.")
            return
        
        liters = state['liters'].get(cow, 0.0)
        bot.answer_callback_query(call.id)
        bot.edit_message_text(
            f"🐄 *Sapi {cow}*\nHasil Susu: *{liters} Liter*\n\nGunakan tombol di bawah untuk menyesuaikan:",
            chat_id=chat_id,
            message_id=call.message.message_id,
            parse_mode="Markdown",
            reply_markup=render_edit_milk_board(cow)
        )

    elif call.data.startswith("adjmilk|"):
        _, cow, amt_str = call.data.split("|")
        amount = float(amt_str)
        
        chat_id = call.message.chat.id
        state = milk_reporting_state.get(chat_id)
        if not state:
            bot.answer_callback_query(call.id, "Sesi habis.")
            return
        
        current = state['liters'].get(cow, 0.0)
        new_amount = max(0.0, round(current + amount, 1))
        state['liters'][cow] = new_amount
        
        bot.answer_callback_query(call.id)
        bot.edit_message_text(
            f"🐄 *Sapi {cow}*\nHasil Susu: *{new_amount} Liter*\n\nGunakan tombol di bawah untuk menyesuaikan:",
            chat_id=chat_id,
            message_id=call.message.message_id,
            parse_mode="Markdown",
            reply_markup=render_edit_milk_board(cow)
        )

    elif call.data == "back_milk_main":
        chat_id = call.message.chat.id
        state = milk_reporting_state.get(chat_id)
        if not state:
            bot.answer_callback_query(call.id, "Sesi habis.")
            return
            
        bot.answer_callback_query(call.id)
        bot.edit_message_text(
            f"📝 *Pencatatan Susu (Kandang {state['barn']})*\nSilakan klik nama sapi untuk mengatur hasil susu (Liter):",
            chat_id=chat_id,
            message_id=call.message.message_id,
            parse_mode="Markdown",
            reply_markup=render_main_milk_board(chat_id)
        )

    elif call.data == "save_milk_report":
        chat_id = call.message.chat.id
        state = milk_reporting_state.get(chat_id)
        if not state:
            bot.answer_callback_query(call.id, "Sesi habis.")
            return
            
        bot.answer_callback_query(call.id, "Menyimpan data susu...")
        
        session = get_session()
        for cow, liters in state['liters'].items():
            cow_obj = session.query(Cow).filter_by(cow_code=cow).first()
            if cow_obj:
                cow_obj.litre_milked_today = liters
        
        today = datetime.now().strftime("%Y-%m-%d")
        telegram_id = call.from_user.id
        session.add(DailyKandangLog(date=today, barn=state['barn'], type='SUSU', telegram_id=telegram_id))
        session.commit()
        Session.remove()
        
        bot.edit_message_text(
            "✅ *Laporan Susu Selesai!*\nSemua data telah disimpan.\nData MRP Susu sedang disinkronisasi...",
            chat_id=chat_id,
            message_id=call.message.message_id,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup()
        )
        del milk_reporting_state[chat_id]
        
        try:
            import financials
            financials.MilkMRP.recalculate()
        except Exception as e:
            print("Gagal hitung ulang MRP Susu:", e)
        
    elif call.data.startswith("lapor_sakit_"):
        barn = call.data.replace("lapor_sakit_", "")
        
        # Ambil daftar sapi di kandang tersebut
        session = get_session()
        cows_q = session.query(Cow).filter(
            Cow.barn == barn,
            ~Cow.status.in_(['SOLD', 'DEAD', 'REJECTED']),
        ).all()
        rows = [(c.cow_code,) for c in cows_q]
        Session.remove()
        
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
        session = get_session()
        cow_obj = session.query(Cow).filter_by(cow_code=cow_code).first()
        if cow_obj: cow_obj.status = 'SICK'
        session.commit()
        Session.remove()
        
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("↩️ Batalkan (Undo)", callback_data=f"undo_sick_{cow_code}"))
        
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, f"✅ Status sapi {cow_code} diubah menjadi SAKIT.", reply_markup=markup)
        
    elif call.data.startswith("markdead_"):
        cow_code = call.data.replace("markdead_", "")
        session = get_session()
        cow_obj = session.query(Cow).filter_by(cow_code=cow_code).first()
        if cow_obj: cow_obj.status = 'DEAD'
        session.commit()
        Session.remove()
        
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("↩️ Batalkan (Undo)", callback_data=f"undo_dead_{cow_code}"))

        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, f"✅ Status sapi {cow_code} diubah menjadi MATI.", reply_markup=markup)
        
    # ===============================
    # UNDO HANDLERS
    # ===============================
    elif call.data.startswith("undo_log_"):
        log_id = call.data.replace("undo_log_", "")
        session = get_session()
        session.query(DailyKandangLog).filter_by(id=int(log_id)).delete()
        session.commit()
        Session.remove()
        
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
        
        session = get_session()
        cow_obj = session.query(Cow).filter_by(cow_code=cow_code).first()
        if cow_obj: cow_obj.status = 'AVAILABLE'
        session.commit()
        Session.remove()
        
        bot.answer_callback_query(call.id, "Status dibatalkan!")
        bot.edit_message_text(
            f"🔄 Status sapi {cow_code} dikembalikan menjadi Normal (*AVAILABLE*).",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="Markdown"
        )
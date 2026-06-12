import telebot

from config import (
    API_TOKEN,
    ABYASA_ID,
    AXEL_ID,
    ELISA_ID,
    RAFIF_ID
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

    bot.send_message(
        message.chat.id,
        f"Halo {message.from_user.first_name}"
    )


@bot.message_handler(commands=['testsapi'])
def test_sapi(message):

    send_new_cow(
    "SPR-001",
    "Pak Budi"
)


@bot.message_handler(commands=['testjual'])
def test_jual(message):

    send_prepare_sale(
        message.chat.id,
        "SPR-001"
    )


@bot.message_handler(commands=['testpo'])
def test_po(message):

    send_feed_order(
        message.chat.id,
        "PO-001",
        100
    )


# =========================
# BOT START
# =========================

def start_bot():

    print("Bot Running...")
    bot.infinity_polling()


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

        bot.send_message(
            target,
            f"""
🐄 PERMINTAAN KANDANG

ID: {cow_id}
Pemilik: {owner}

Apakah masih ada kapasitas?
""",
            reply_markup=markup
        )


# =========================
# PREPARE SALE
# =========================

def send_prepare_sale(chat_id, cow_id):

    markup = InlineKeyboardMarkup()

    btn_prepare = InlineKeyboardButton(
        "🚚 Siap",
        callback_data=f"prepare_{cow_id}"
    )

    btn_sold = InlineKeyboardButton(
        "💰 Terjual",
        callback_data=f"sold_{cow_id}"
    )

    markup.add(btn_prepare)
    markup.add(btn_sold)

    bot.send_message(
        chat_id,
        f"""
🚚 SIAPKAN TERNAK

ID: {cow_id}

Pembeli akan datang.
""",
        reply_markup=markup
    )


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

    bot.send_message(
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


# =========================
# CALLBACK HANDLER
# =========================

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):

    # TERIMA SAPI
    if call.data.startswith("accept_"):

        cow_id = call.data.replace(
            "accept_",
            ""
        )

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

        if telegram_id == ABYASA_ID:
            caretaker = "ABYASA"
        elif telegram_id == AXEL_ID:
            caretaker = "AXEL"
        else:
            caretaker = "UNKNOWN"

        cursor.execute(
            """
            UPDATE cows
            SET caretaker = ?,
                status = ?
            WHERE cow_code = ?
            """,
            (
                caretaker,
                "WAITING_FOR_ARRIVAL",
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
{caretaker}

Status:
WAITING_FOR_ARRIVAL
"""
        )

        print(
            f"{cow_id} -> {caretaker}"
        )

    # TOLAK / PENUH
    elif call.data.startswith("reject_"):

        cow_id = call.data.replace(
            "reject_",
            ""
        )

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


    # SIAP JUAL
    elif call.data.startswith("prepare_"):

        cow_id = call.data.replace(
            "prepare_",
            ""
        )

        cursor.execute(
            """
            UPDATE cows
            SET status = ?
            WHERE cow_code = ?
            """,
            (
                "READY_FOR_PICKUP",
                cow_id
            )
        )

        conn.commit()

        bot.answer_callback_query(call.id)

        bot.send_message(
            call.message.chat.id,
            f"🚚 {cow_id} siap dijual."
        )

        print(f"{cow_id} READY_FOR_PICKUP")

    elif call.data.startswith("sold_"):

        cow_id = call.data.replace(
            "sold_",
            ""
        )

        cursor.execute(
            """
            UPDATE cows
            SET status = ?
            WHERE cow_code = ?
            """,
            (
                "SOLD",
                cow_id
            )
        )

        conn.commit()

        bot.answer_callback_query(call.id)

        bot.send_message(
            call.message.chat.id,
            f"💰 {cow_id} berhasil terjual."
        )

        print(f"{cow_id} SOLD")



    # PO DISETUJUI
    elif call.data.startswith("confirmpo_"):

        po_id = call.data.replace(
            "confirmpo_",
            ""
        )

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

        po_id = call.data.replace(
            "rejectpo_",
            ""
        )

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
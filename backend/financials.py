import datetime
from database import db_fetch_all, db_fetch_one, db_execute


# ──────────────────────────────────────────────────────────────
# CONFIG HELPER — reads all values from koperasi_config table
# ──────────────────────────────────────────────────────────────

def get_koperasi_config():
    """Fetch all koperasi_config rows as a dict {key: value}."""
    rows = db_fetch_all("SELECT key, value FROM koperasi_config")
    config = {}
    for key, value in rows:
        config[key] = value
    return config


# ──────────────────────────────────────────────────────────────
# FEED MRP
# ──────────────────────────────────────────────────────────────

class FeedMRP:
    @staticmethod
    def get_feed_report():
        config = get_koperasi_config()

        # Get all cows (not just ACTIVE — we count all non-SOLD)
        cows = db_fetch_all("SELECT weight FROM cows WHERE status != 'SOLD'")
        total_weight = sum(cow[0] for cow in cows if cow[0]) if cows else 0
        active_cows_count = len(cows)

        # Feed requirement: approx 3% of body weight per day
        daily_feed_needed_kg = total_weight * 0.03

        # Get current feed price from history (latest)
        latest_price_row = db_fetch_one("SELECT price_per_kg FROM feed_price_history ORDER BY date DESC LIMIT 1")
        current_price_per_kg = latest_price_row[0] if latest_price_row else 1000.0

        daily_feed_cost = daily_feed_needed_kg * current_price_per_kg

        # Mock current stock since there is no inventory table yet
        current_stock_kg = 2300.0

        # Fetch history for chart
        history = db_fetch_all("SELECT date, price_per_kg, total_kg FROM feed_financials ORDER BY date ASC")

        return {
            "active_cows": active_cows_count,
            "total_weight_kg": total_weight,
            "daily_feed_needed_kg": daily_feed_needed_kg,
            "current_stock_kg": current_stock_kg,
            "current_price_per_kg": current_price_per_kg,
            "daily_feed_cost": daily_feed_cost,
            "history": [{"date": r[0], "price": r[1], "total_kg": r[2]} for r in history]
        }


# ──────────────────────────────────────────────────────────────
# MILK MRP
# ──────────────────────────────────────────────────────────────

class MilkMRP:
    @staticmethod
    def get_milk_report():
        config = get_koperasi_config()

        # Get today's total milk production from cows table
        cows = db_fetch_all("SELECT litre_milked_today FROM cows WHERE status != 'SOLD'")
        total_liters_today = sum(cow[0] for cow in cows if cow[0]) if cows else 0

        milk_price = config.get('harga_susu_per_liter', 6500.0)
        estimated_revenue_today = total_liters_today * milk_price

        # Update or insert today's milk financial log
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        existing_log = db_fetch_one("SELECT id FROM milk_financials WHERE date = ?", (today_str,))

        if existing_log:
            db_execute(
                "UPDATE milk_financials SET total_liters = ?, price_per_liter = ?, estimated_revenue = ? WHERE date = ?",
                (total_liters_today, milk_price, estimated_revenue_today, today_str)
            )
        else:
            db_execute(
                "INSERT INTO milk_financials (date, total_liters, price_per_liter, estimated_revenue) VALUES (?, ?, ?, ?)",
                (today_str, total_liters_today, milk_price, estimated_revenue_today)
            )

        # Fetch history
        history = db_fetch_all("SELECT date, total_liters, estimated_revenue FROM milk_financials ORDER BY date ASC")

        return {
            "total_liters_today": total_liters_today,
            "milk_price": milk_price,
            "estimated_revenue_today": estimated_revenue_today,
            "history": [{"date": r[0], "liters": r[1], "revenue": r[2]} for r in history]
        }

    @staticmethod
    def recalculate():
        # Called when milk production is updated via telegram
        MilkMRP.get_milk_report()


# ──────────────────────────────────────────────────────────────
# WASTE / FERTILIZER MRP
# ──────────────────────────────────────────────────────────────

class WasteMRP:
    @staticmethod
    def get_waste_report():
        config = get_koperasi_config()

        cows = db_fetch_all("SELECT id FROM cows WHERE status != 'SOLD'")
        active_cows_count = len(cows)

        daily_waste_kg_fresh = active_cows_count * config.get('produksi_limbah_per_hari', 10.0)
        rasio = config.get('rasio_fermentasi', 0.6)
        daily_fertilizer_kg = daily_waste_kg_fresh * rasio

        # Fertilizer price from config
        current_price_per_kg = config.get('harga_pupuk_per_kg', 5000.0)

        # Processing batches
        batches = db_fetch_all("SELECT id, date_collected, kg_amount, status, ready_date FROM waste_processing ORDER BY ready_date ASC")

        # Check if any batch is ready
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        for b in batches:
            if b[3] == 'FERMENTING' and b[4] <= today_str:
                db_execute("UPDATE waste_processing SET status = 'READY' WHERE id = ?", (b[0],))

        # Refetch batches after update
        batches = db_fetch_all("SELECT id, date_collected, kg_amount, status, ready_date FROM waste_processing ORDER BY ready_date ASC")

        # Ready fertilizer amount
        ready_batches = [b for b in batches if b[3] == 'READY']
        total_ready_kg = sum(b[2] for b in ready_batches)

        # History
        history = db_fetch_all("SELECT date, price_per_kg, total_kg_fertilizer FROM waste_financials ORDER BY date ASC")

        return {
            "active_cows": active_cows_count,
            "daily_waste_kg_fresh": daily_waste_kg_fresh,
            "daily_fertilizer_kg": daily_fertilizer_kg,
            "current_price_per_kg": current_price_per_kg,
            "total_ready_kg": total_ready_kg,
            "batches": [{"id": r[0], "date_collected": r[1], "kg_amount": r[2], "status": r[3], "ready_date": r[4]} for r in batches],
            "history": [{"date": r[0], "price": r[1], "fertilizer": r[2]} for r in history]
        }

    @staticmethod
    def collect_daily_waste():
        config = get_koperasi_config()
        cows = db_fetch_all("SELECT id FROM cows WHERE status != 'SOLD'")
        active_cows_count = len(cows)
        if active_cows_count == 0:
            return

        daily_waste_kg = active_cows_count * config.get('produksi_limbah_per_hari', 10.0)
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        ready_date_str = (datetime.date.today() + datetime.timedelta(days=14)).strftime("%Y-%m-%d")

        # Prevent double collection on same day
        existing = db_fetch_one("SELECT id FROM waste_processing WHERE date_collected = ?", (today_str,))
        if not existing:
            db_execute(
                "INSERT INTO waste_processing (date_collected, kg_amount, status, ready_date) VALUES (?, ?, 'FERMENTING', ?)",
                (today_str, daily_waste_kg, ready_date_str)
            )


# ──────────────────────────────────────────────────────────────
# OPERATIONAL MRP — with 60/40 profit sharing
# ──────────────────────────────────────────────────────────────

class OperationalMRP:
    @staticmethod
    def get_operational_report(months_multiplier=1):
        config = get_koperasi_config()

        # Jumlah sapi (non-SOLD)
        total_sapi_row = db_fetch_one("SELECT COUNT(*) FROM cows WHERE status != 'SOLD'")
        total_sapi = total_sapi_row[0] if total_sapi_row else 0

        # Keanggotaan
        members_data = db_fetch_all('''
            SELECT m.role, m.iuran_pokok,
                   (SELECT COUNT(*) FROM cows c WHERE c.owner_id = m.id AND c.status != 'SOLD') as cow_count
            FROM members m
        ''')
        total_anggota = len(members_data)

        # Simpanan Pokok — ekuitas, dibayar sekali seumur hidup (TIDAK masuk laba rugi)
        simpanan_pokok_total = total_anggota * config.get('simpanan_pokok', 1500000.0)

        # Simpanan Wajib — per SAPI per bulan (masuk pendapatan koperasi)
        simpanan_wajib_per_sapi = config.get('simpanan_wajib_per_sapi', 200000.0)
        simpanan_wajib_total = total_sapi * simpanan_wajib_per_sapi * months_multiplier

        # ── Biaya Operasional (dari config, bisa diubah admin) ──
        biaya_pakan = config.get('pakan_per_sapi', 750000.0) * total_sapi * months_multiplier
        gaji_pekerja = config.get('jumlah_pekerja', 5.0) * config.get('gaji_per_pekerja', 3800000.0) * months_multiplier
        biaya_karung = config.get('biaya_karung', 350000.0) * months_multiplier
        biaya_em4 = config.get('biaya_fermentasi_em4', 202000.0) * months_multiplier
        biaya_distribusi = config.get('biaya_distribusi_susu', 800000.0) * months_multiplier
        biaya_utilitas = config.get('biaya_utilitas', 500000.0) * months_multiplier

        total_biaya_ops = biaya_pakan + gaji_pekerja + biaya_karung + biaya_em4 + biaya_distribusi + biaya_utilitas

        return {
            "total_sapi": total_sapi,
            "total_anggota": total_anggota,
            # Keanggotaan (simpanan pokok = ekuitas, bukan laba rugi)
            "simpanan_pokok_total": simpanan_pokok_total,
            "simpanan_wajib_total": simpanan_wajib_total,
            # Biaya operasional detail
            "biaya_pakan": biaya_pakan,
            "gaji_pekerja": gaji_pekerja,
            "biaya_karung": biaya_karung,
            "biaya_em4": biaya_em4,
            "biaya_distribusi": biaya_distribusi,
            "biaya_utilitas": biaya_utilitas,
            "total_biaya_ops": total_biaya_ops,
            # Config reference
            "config": {
                "bagi_hasil_koperasi": config.get('bagi_hasil_koperasi', 0.6),
                "bagi_hasil_pemilik": config.get('bagi_hasil_pemilik', 0.4),
                "jumlah_pekerja": config.get('jumlah_pekerja', 5.0),
                "gaji_per_pekerja": config.get('gaji_per_pekerja', 3800000.0),
                "pakan_per_sapi": config.get('pakan_per_sapi', 750000.0),
            }
        }


# ──────────────────────────────────────────────────────────────
# AGGREGATE REPORT — combines all MRP + 60/40 profit sharing
# ──────────────────────────────────────────────────────────────

def get_aggregate_report(period="all"):
    today = datetime.date.today()
    config = get_koperasi_config()

    end_date = today.strftime("%Y-%m-%d")

    if period == "30":
        start_date = (today - datetime.timedelta(days=30)).strftime("%Y-%m-%d")
        months_multiplier = 1
    elif period == "90":
        start_date = (today - datetime.timedelta(days=90)).strftime("%Y-%m-%d")
        months_multiplier = 3
    elif period == "365":
        start_date = (today - datetime.timedelta(days=365)).strftime("%Y-%m-%d")
        months_multiplier = 12
    else:  # all
        start_date = "2000-01-01"
        end_date = "9999-12-31"
        months_multiplier = 12

    feed_report = FeedMRP.get_feed_report()
    milk_report = MilkMRP.get_milk_report()
    waste_report = WasteMRP.get_waste_report()
    ops_report = OperationalMRP.get_operational_report(months_multiplier)

    # ── Pendapatan Kotor dari Database ──
    milk_monthly = db_fetch_one("SELECT SUM(estimated_revenue) FROM milk_financials WHERE date >= ? AND date <= ?", (start_date, end_date))
    real_milk_revenue = milk_monthly[0] if milk_monthly and milk_monthly[0] else 0.0

    waste_monthly = db_fetch_one("SELECT SUM(estimated_revenue) FROM waste_financials WHERE date >= ? AND date <= ?", (start_date, end_date))
    real_waste_revenue = waste_monthly[0] if waste_monthly and waste_monthly[0] else 0.0

    feed_monthly = db_fetch_one("SELECT SUM(estimated_cost) FROM feed_financials WHERE date >= ? AND date <= ?", (start_date, end_date))
    real_feed_cost = feed_monthly[0] if feed_monthly and feed_monthly[0] else 0.0

    ops_monthly = db_fetch_one("SELECT SUM(amount) FROM operational_transactions WHERE date >= ? AND date <= ?", (start_date, end_date))
    real_ops_cost = ops_monthly[0] if ops_monthly and ops_monthly[0] else 0.0

    # ── Skema Bagi Hasil 60/40 ──
    bagi_koperasi = config.get('bagi_hasil_koperasi', 0.6)
    bagi_pemilik = config.get('bagi_hasil_pemilik', 0.4)

    # Bagian koperasi dari penjualan
    bagian_koperasi_susu = real_milk_revenue * bagi_koperasi
    bagian_pemilik_susu = real_milk_revenue * bagi_pemilik
    bagian_koperasi_pupuk = real_waste_revenue * bagi_koperasi
    bagian_pemilik_pupuk = real_waste_revenue * bagi_pemilik

    # Total pendapatan koperasi = bagian 60% + simpanan wajib
    total_pendapatan_koperasi = bagian_koperasi_susu + bagian_koperasi_pupuk + ops_report["simpanan_wajib_total"]

    # Total pengeluaran koperasi = biaya operasional (dari config)
    total_pengeluaran_koperasi = ops_report["total_biaya_ops"]

    # Laba bersih koperasi
    laba_koperasi = total_pendapatan_koperasi - total_pengeluaran_koperasi

    # ── Per Sapi per Bulan (untuk info) ──
    total_sapi = ops_report["total_sapi"]
    if total_sapi > 0 and months_multiplier > 0:
        pendapatan_kotor_per_sapi = (real_milk_revenue + real_waste_revenue) / total_sapi / months_multiplier
        bagian_pemilik_per_sapi = (bagian_pemilik_susu + bagian_pemilik_pupuk) / total_sapi / months_multiplier
        simpanan_wajib_per_sapi = config.get('simpanan_wajib_per_sapi', 200000.0)
        net_pemilik_per_sapi = bagian_pemilik_per_sapi - simpanan_wajib_per_sapi
    else:
        pendapatan_kotor_per_sapi = 0
        bagian_pemilik_per_sapi = 0
        net_pemilik_per_sapi = 0

    return {
        "feed": feed_report,
        "milk": milk_report,
        "waste": waste_report,
        "operational": ops_report,
        "bagi_hasil": {
            "persen_koperasi": bagi_koperasi * 100,
            "persen_pemilik": bagi_pemilik * 100,
            # Susu
            "pendapatan_susu_kotor": real_milk_revenue,
            "bagian_koperasi_susu": bagian_koperasi_susu,
            "bagian_pemilik_susu": bagian_pemilik_susu,
            # Pupuk
            "pendapatan_pupuk_kotor": real_waste_revenue,
            "bagian_koperasi_pupuk": bagian_koperasi_pupuk,
            "bagian_pemilik_pupuk": bagian_pemilik_pupuk,
            # Per sapi
            "pendapatan_kotor_per_sapi": pendapatan_kotor_per_sapi,
            "bagian_pemilik_per_sapi": bagian_pemilik_per_sapi,
            "net_pemilik_per_sapi": net_pemilik_per_sapi,
        },
        "summary": {
            "real_milk_revenue": real_milk_revenue,
            "real_waste_revenue": real_waste_revenue,
            "real_feed_cost": real_feed_cost,
            "real_ops_cost": real_ops_cost,
            # Koperasi financials
            "total_pendapatan_koperasi": total_pendapatan_koperasi,
            "total_pengeluaran_koperasi": total_pengeluaran_koperasi,
            "laba_koperasi": laba_koperasi,
            # Legacy keys (for backward compat with transaksi page)
            "total_revenue_estimasi": real_milk_revenue + real_waste_revenue,
            "total_expense_estimasi": total_pengeluaran_koperasi,
            "net_profit_estimasi": laba_koperasi,
        }
    }

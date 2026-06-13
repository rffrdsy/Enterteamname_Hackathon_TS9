"""
Financial MRP logic with 60/40 profit sharing — ORM version.
"""
import datetime
# pyrefly: ignore [missing-import]
from sqlalchemy import func
from models import (
    get_session, Session,
    Cow, Member, KoperasiConfig,
    FeedFinancial, MilkFinancial, WasteFinancial,
    WasteProcessing, OperationalTransaction, FeedPriceHistory,
)


# ──────────────────────────────────────────────────────────────
# CONFIG HELPER
# ──────────────────────────────────────────────────────────────

def get_koperasi_config():
    """Fetch all koperasi_config rows as a dict {key: value}."""
    session = get_session()
    try:
        rows = session.query(KoperasiConfig).all()
        return {r.key: r.value for r in rows}
    finally:
        Session.remove()


# ──────────────────────────────────────────────────────────────
# FEED MRP
# ──────────────────────────────────────────────────────────────

class FeedMRP:
    @staticmethod
    def get_feed_report():
        config = get_koperasi_config()
        session = get_session()
        try:
            cows = session.query(Cow).filter(Cow.status != "SOLD").all()
            total_weight = sum(c.weight or 0 for c in cows)
            active_cows_count = len(cows)

            daily_feed_needed_kg = total_weight * 0.03

            latest = session.query(FeedPriceHistory).order_by(
                FeedPriceHistory.date.desc()
            ).first()
            current_price_per_kg = latest.price_per_kg if latest else 1000.0

            daily_feed_cost = daily_feed_needed_kg * current_price_per_kg
            current_stock_kg = 2300.0

            history = session.query(FeedPriceHistory).order_by(FeedPriceHistory.date.asc()).all()

            return {
                "active_cows": active_cows_count,
                "total_weight_kg": total_weight,
                "daily_feed_needed_kg": daily_feed_needed_kg,
                "current_stock_kg": current_stock_kg,
                "current_price_per_kg": current_price_per_kg,
                "daily_feed_cost": daily_feed_cost,
                "history": [{"date": r.date, "price": r.price_per_kg} for r in history],
            }
        finally:
            Session.remove()


# ──────────────────────────────────────────────────────────────
# MILK MRP
# ──────────────────────────────────────────────────────────────

class MilkMRP:
    @staticmethod
    def get_milk_report():
        config = get_koperasi_config()
        session = get_session()
        try:
            cows = session.query(Cow).filter(Cow.status != "SOLD").all()
            total_liters_today = sum(c.litre_milked_today or 0 for c in cows)

            milk_price = config.get("harga_susu_per_liter", 6500.0)
            estimated_revenue_today = total_liters_today * milk_price

            today_str = datetime.date.today().strftime("%Y-%m-%d")
            existing = session.query(MilkFinancial).filter_by(date=today_str).first()

            if existing:
                existing.total_liters = total_liters_today
                existing.price_per_liter = milk_price
                existing.estimated_revenue = estimated_revenue_today
            else:
                session.add(MilkFinancial(
                    date=today_str,
                    total_liters=total_liters_today,
                    price_per_liter=milk_price,
                    estimated_revenue=estimated_revenue_today,
                ))
            session.commit()

            history = session.query(MilkFinancial).order_by(MilkFinancial.date.asc()).all()

            return {
                "total_liters_today": total_liters_today,
                "milk_price": milk_price,
                "estimated_revenue_today": estimated_revenue_today,
                "history": [{"date": r.date, "liters": r.total_liters, "revenue": r.estimated_revenue} for r in history],
            }
        finally:
            Session.remove()

    @staticmethod
    def recalculate():
        MilkMRP.get_milk_report()


# ──────────────────────────────────────────────────────────────
# WASTE / FERTILIZER MRP
# ──────────────────────────────────────────────────────────────

class WasteMRP:
    @staticmethod
    def get_waste_report():
        config = get_koperasi_config()
        session = get_session()
        try:
            active_cows_count = session.query(Cow).filter(Cow.status != "SOLD").count()

            daily_waste_fresh = active_cows_count * config.get("produksi_limbah_per_hari", 10.0)
            rasio = config.get("rasio_fermentasi", 0.6)
            daily_fertilizer_kg = daily_waste_fresh * rasio

            current_price_per_kg = config.get("harga_pupuk_per_kg", 5000.0)

            today_str = datetime.date.today().strftime("%Y-%m-%d")

            # Auto-update fermenting → ready
            fermenting = session.query(WasteProcessing).filter(
                WasteProcessing.status == "FERMENTING",
                WasteProcessing.ready_date <= today_str,
            ).all()
            for b in fermenting:
                b.status = "READY"
            if fermenting:
                session.commit()

            batches = session.query(WasteProcessing).order_by(WasteProcessing.ready_date.asc()).all()

            ready_batches = [b for b in batches if b.status == "READY"]
            total_ready_kg = sum(b.kg_amount for b in ready_batches)

            history = session.query(WasteFinancial).order_by(WasteFinancial.date.asc()).all()

            return {
                "active_cows": active_cows_count,
                "daily_waste_kg_fresh": daily_waste_fresh,
                "daily_fertilizer_kg": daily_fertilizer_kg,
                "current_price_per_kg": current_price_per_kg,
                "total_ready_kg": total_ready_kg,
                "batches": [
                    {"id": b.id, "date_collected": b.date_collected, "kg_amount": b.kg_amount,
                     "status": b.status, "ready_date": b.ready_date}
                    for b in batches
                ],
                "history": [{"date": r.date, "price": r.price_per_kg, "fertilizer": r.total_kg_fertilizer} for r in history],
            }
        finally:
            Session.remove()

    @staticmethod
    def collect_daily_waste():
        config = get_koperasi_config()
        session = get_session()
        try:
            active_count = session.query(Cow).filter(Cow.status != "SOLD").count()
            if active_count == 0:
                return

            daily_kg = active_count * config.get("produksi_limbah_per_hari", 10.0)
            today_str = datetime.date.today().strftime("%Y-%m-%d")
            ready_str = (datetime.date.today() + datetime.timedelta(days=14)).strftime("%Y-%m-%d")

            existing = session.query(WasteProcessing).filter_by(date_collected=today_str).first()
            if not existing:
                session.add(WasteProcessing(
                    date_collected=today_str,
                    kg_amount=daily_kg,
                    status="FERMENTING",
                    ready_date=ready_str,
                ))
                session.commit()
        finally:
            Session.remove()


# ──────────────────────────────────────────────────────────────
# OPERATIONAL MRP — with 60/40 profit sharing
# ──────────────────────────────────────────────────────────────

class OperationalMRP:
    @staticmethod
    def get_operational_report(months_multiplier=1):
        config = get_koperasi_config()
        session = get_session()
        try:
            total_sapi = session.query(Cow).filter(Cow.status != "SOLD").count()
            members = session.query(Member).all()
            total_anggota = len(members)

            simpanan_pokok_total = total_anggota * config.get("simpanan_pokok", 1500000.0)
            simpanan_wajib_per_sapi = config.get("simpanan_wajib_per_sapi", 200000.0)
            simpanan_wajib_total = total_sapi * simpanan_wajib_per_sapi * months_multiplier

            biaya_pakan = config.get("pakan_per_sapi", 1000000.0) * total_sapi * months_multiplier
            
            # The user explicitly requested fixed 5 workers and these fixed costs
            gaji_pekerja = config.get("jumlah_pekerja", 5.0) * config.get("gaji_per_pekerja", 3800000.0) * months_multiplier
            biaya_karung = config.get("biaya_karung", 350000.0) * months_multiplier
            biaya_em4 = config.get("biaya_fermentasi_em4", 202000.0) * months_multiplier
            biaya_distribusi = config.get("biaya_distribusi_susu", 800000.0) * months_multiplier
            biaya_utilitas = config.get("biaya_utilitas", 500000.0) * months_multiplier
            
            total_biaya_ops = biaya_pakan + gaji_pekerja + biaya_karung + biaya_em4 + biaya_distribusi + biaya_utilitas

            return {
                "total_sapi": total_sapi,
                "total_anggota": total_anggota,
                "simpanan_pokok_total": simpanan_pokok_total,
                "simpanan_wajib_total": simpanan_wajib_total,
                "biaya_pakan": biaya_pakan,
                "gaji_pekerja": gaji_pekerja,
                "biaya_karung": biaya_karung,
                "biaya_em4": biaya_em4,
                "biaya_distribusi": biaya_distribusi,
                "biaya_utilitas": biaya_utilitas,
                "total_biaya_ops": total_biaya_ops,
                "config": {
                    "bagi_hasil_koperasi": config.get("bagi_hasil_koperasi", 0.3),
                    "bagi_hasil_pemilik": config.get("bagi_hasil_pemilik", 0.7),
                    "jumlah_pekerja": config.get("jumlah_pekerja", 5.0),
                    "gaji_per_pekerja": config.get("gaji_per_pekerja", 3800000.0),
                    "pakan_per_sapi": config.get("pakan_per_sapi", 1000000.0),
                    "simpanan_wajib_per_sapi": simpanan_wajib_per_sapi,
                },
            }
        finally:
            Session.remove()


# ──────────────────────────────────────────────────────────────
# AGGREGATE REPORT
# ──────────────────────────────────────────────────────────────

def get_aggregate_report(period="all"):
    today = datetime.date.today()
    config = get_koperasi_config()
    session = get_session()

    try:
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
        else:
            # "all" — calculate months from actual data span
            earliest = session.query(func.min(MilkFinancial.date)).scalar()
            if earliest:
                try:
                    earliest_dt = datetime.datetime.strptime(earliest, "%Y-%m-%d").date()
                    days_span = max(1, (today - earliest_dt).days)
                    months_multiplier = max(1, round(days_span / 30))
                except Exception:
                    months_multiplier = 1
            else:
                months_multiplier = 1
            start_date = "2000-01-01"
            end_date = "9999-12-31"

        feed_report = FeedMRP.get_feed_report()
        milk_report = MilkMRP.get_milk_report()
        waste_report = WasteMRP.get_waste_report()
        ops_report = OperationalMRP.get_operational_report(months_multiplier)

        # Revenue projected based on current daily run rate to match the extrapolated expenses
        days_in_period = 30 if period == "30" else 90 if period == "90" else 365 if period == "365" else max(1, months_multiplier * 30)

        daily_milk_revenue = milk_report.get("estimated_revenue_today", 0.0)
        daily_waste_revenue = waste_report.get("daily_fertilizer_kg", 0.0) * waste_report.get("current_price_per_kg", 0.0)

        milk_sum = daily_milk_revenue * days_in_period
        waste_sum = daily_waste_revenue * days_in_period

        feed_sum = session.query(func.sum(FeedFinancial.estimated_cost)).filter(
            FeedFinancial.date >= start_date, FeedFinancial.date <= end_date
        ).scalar() or 0.0

        ops_sum = session.query(func.sum(OperationalTransaction.amount)).filter(
            OperationalTransaction.date >= start_date, OperationalTransaction.date <= end_date
        ).scalar() or 0.0

        # 30/70 split
        bagi_koperasi = config.get("bagi_hasil_koperasi", 0.3)
        bagi_pemilik = config.get("bagi_hasil_pemilik", 0.7)

        bagian_koperasi_susu = milk_sum * bagi_koperasi
        bagian_pemilik_susu = milk_sum * bagi_pemilik
        bagian_koperasi_pupuk = waste_sum * bagi_koperasi
        bagian_pemilik_pupuk = waste_sum * bagi_pemilik

        total_pendapatan_koperasi = bagian_koperasi_susu + bagian_koperasi_pupuk + ops_report["simpanan_wajib_total"]
        total_pengeluaran_koperasi = ops_report["total_biaya_ops"]
        laba_koperasi = total_pendapatan_koperasi - total_pengeluaran_koperasi

        total_sapi = ops_report["total_sapi"]
        if total_sapi > 0 and months_multiplier > 0:
            pendapatan_kotor_per_sapi = (milk_sum + waste_sum) / total_sapi / months_multiplier
            bagian_pemilik_per_sapi = (bagian_pemilik_susu + bagian_pemilik_pupuk) / total_sapi / months_multiplier
            sw = config.get("simpanan_wajib_per_sapi", 200000.0)
            net_pemilik_per_sapi = bagian_pemilik_per_sapi - sw
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
                "pendapatan_susu_kotor": milk_sum,
                "bagian_koperasi_susu": bagian_koperasi_susu,
                "bagian_pemilik_susu": bagian_pemilik_susu,
                "pendapatan_pupuk_kotor": waste_sum,
                "bagian_koperasi_pupuk": bagian_koperasi_pupuk,
                "bagian_pemilik_pupuk": bagian_pemilik_pupuk,
                "pendapatan_kotor_per_sapi": pendapatan_kotor_per_sapi,
                "bagian_pemilik_per_sapi": bagian_pemilik_per_sapi,
                "net_pemilik_per_sapi": net_pemilik_per_sapi,
            },
            "summary": {
                "real_milk_revenue": milk_sum,
                "real_waste_revenue": waste_sum,
                "real_feed_cost": feed_sum,
                "real_ops_cost": ops_sum,
                "total_pendapatan_koperasi": total_pendapatan_koperasi,
                "total_pengeluaran_koperasi": total_pengeluaran_koperasi,
                "laba_koperasi": laba_koperasi,
                "total_revenue_estimasi": milk_sum + waste_sum,
                "total_expense_estimasi": total_pengeluaran_koperasi,
                "net_profit_estimasi": laba_koperasi,
            },
        }
    finally:
        Session.remove()

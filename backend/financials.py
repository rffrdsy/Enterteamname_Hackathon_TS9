import datetime
from database import db_fetch_all, db_fetch_one, db_execute

class FeedMRP:
    @staticmethod
    def get_feed_report():
        # Get active cows count and total weight
        cows = db_fetch_all("SELECT weight FROM cows WHERE status = 'ACTIVE'")
        total_weight = sum(cow[0] for cow in cows) if cows else 0
        active_cows_count = len(cows)

        # Feed requirement: approx 3% of body weight per day
        daily_feed_needed_kg = total_weight * 0.03
        
        # Get current feed price from history (latest)
        latest_price_row = db_fetch_one("SELECT price_per_kg FROM feed_price_history ORDER BY date DESC LIMIT 1")
        current_price_per_kg = latest_price_row[0] if latest_price_row else 5000.0

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

class MilkMRP:
    @staticmethod
    def get_milk_report():
        # Get today's total milk production from cows table
        cows = db_fetch_all("SELECT litre_milked_today FROM cows WHERE status = 'ACTIVE'")
        total_liters_today = sum(cow[0] for cow in cows if cow[0]) if cows else 0
        
        milk_price = 6500.0 # Market price
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

class WasteMRP:
    @staticmethod
    def get_waste_report():
        # 1 cow = 5kg waste/day. Fermentation takes 14 days.
        cows = db_fetch_all("SELECT id FROM cows WHERE status = 'ACTIVE'")
        active_cows_count = len(cows)

        daily_waste_kg = active_cows_count * 5.0
        
        # Latest fertilizer price
        latest_price_row = db_fetch_one("SELECT price_per_kg FROM waste_financials ORDER BY date DESC LIMIT 1")
        current_price_per_kg = latest_price_row[0] if latest_price_row else 1500.0

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
            "daily_waste_kg": daily_waste_kg,
            "current_price_per_kg": current_price_per_kg,
            "total_ready_kg": total_ready_kg,
            "batches": [{"id": r[0], "date_collected": r[1], "kg_amount": r[2], "status": r[3], "ready_date": r[4]} for r in batches],
            "history": [{"date": r[0], "price": r[1], "fertilizer": r[2]} for r in history]
        }

    @staticmethod
    def collect_daily_waste():
        # Logic to be run once a day to collect waste into a new batch
        cows = db_fetch_all("SELECT id FROM cows WHERE status = 'ACTIVE'")
        active_cows_count = len(cows)
        if active_cows_count == 0: return

        daily_waste_kg = active_cows_count * 5.0
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        ready_date_str = (datetime.date.today() + datetime.timedelta(days=14)).strftime("%Y-%m-%d")
        
        # Prevent double collection on same day
        existing = db_fetch_one("SELECT id FROM waste_processing WHERE date_collected = ?", (today_str,))
        if not existing:
            db_execute(
                "INSERT INTO waste_processing (date_collected, kg_amount, status, ready_date) VALUES (?, ?, 'FERMENTING', ?)",
                (today_str, daily_waste_kg, ready_date_str)
            )

class OperationalMRP:
    @staticmethod
    def get_operational_report(months_multiplier=1):
        cows = db_fetch_all("SELECT id FROM cows WHERE status = 'ACTIVE'")
        active_cows_count = len(cows)
        
        # Keanggotaan
        members_data = db_fetch_all('''
            SELECT m.role, m.iuran_pokok, 
                   (SELECT COUNT(*) FROM cows c WHERE c.owner_id = m.id) as cow_count 
            FROM members m
        ''')
        simpanan_pokok_total = len(members_data) * 100000.0
        simpanan_wajib_total = len(members_data) * 200000.0 * months_multiplier

        # Gaji Penanggung Jawab
        pj_count = sum(1 for m in members_data if m[0] == 'Penanggungjawab Ternak')
        gaji_pj_kandang = pj_count * 2000000.0 * months_multiplier
        
        # Jaminan Kesehatan
        jaminan_kesehatan = active_cows_count * 50000.0 * months_multiplier
        
        # Operasional Lainnya
        operasional_lain = 500000.0 * months_multiplier

        return {
            "active_cows": active_cows_count,
            "simpanan_pokok_total": simpanan_pokok_total,
            "simpanan_wajib_total": simpanan_wajib_total,
            "gaji_pj_kandang": gaji_pj_kandang,
            "jaminan_kesehatan": jaminan_kesehatan,
            "operasional_lain": operasional_lain
        }

def get_aggregate_report(period="all"):
    import datetime
    today = datetime.date.today()
    
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
    else: # all
        start_date = "2000-01-01"
        end_date = "9999-12-31"
        months_multiplier = 12

    feed_report = FeedMRP.get_feed_report()
    milk_report = MilkMRP.get_milk_report()
    waste_report = WasteMRP.get_waste_report()
    ops_report = OperationalMRP.get_operational_report(months_multiplier)
    
    # Penjualan Susu
    milk_monthly = db_fetch_one("SELECT SUM(estimated_revenue) FROM milk_financials WHERE date >= ? AND date <= ?", (start_date, end_date))
    real_milk_revenue = milk_monthly[0] if milk_monthly and milk_monthly[0] else 0.0
    
    # Penjualan Pupuk
    waste_monthly = db_fetch_one("SELECT SUM(estimated_revenue) FROM waste_financials WHERE date >= ? AND date <= ?", (start_date, end_date))
    real_waste_revenue = waste_monthly[0] if waste_monthly and waste_monthly[0] else 0.0
    
    # Beli Pakan Ternak
    feed_monthly = db_fetch_one("SELECT SUM(estimated_expense) FROM feed_financials WHERE date >= ? AND date <= ?", (start_date, end_date))
    real_feed_cost = feed_monthly[0] if feed_monthly and feed_monthly[0] else 0.0
    
    # Operasional Lainnya
    ops_monthly = db_fetch_one("SELECT SUM(amount) FROM operational_transactions WHERE date >= ? AND date <= ?", (start_date, end_date))
    real_ops_cost = ops_monthly[0] if ops_monthly and ops_monthly[0] else 0.0
    
    # Override hardcoded operasional_lain with real database sum (but fallback to ops_report multiplier if no real ops_cost found)
    ops_report["operasional_lain"] = real_ops_cost if real_ops_cost > 0 else (500000.0 * months_multiplier)

    total_revenue_estimasi = real_milk_revenue + real_waste_revenue
    total_expense_estimasi = real_feed_cost + ops_report["gaji_pj_kandang"] + ops_report["jaminan_kesehatan"] + ops_report["operasional_lain"]
    net_profit_estimasi = total_revenue_estimasi - total_expense_estimasi

    return {
        "feed": feed_report,
        "milk": milk_report,
        "waste": waste_report,
        "operational": ops_report,
        "summary": {
            "real_milk_revenue": real_milk_revenue,
            "real_waste_revenue": real_waste_revenue,
            "real_feed_cost": real_feed_cost,
            "real_ops_cost": real_ops_cost,
            "total_revenue_estimasi": total_revenue_estimasi,
            "total_expense_estimasi": total_expense_estimasi,
            "net_profit_estimasi": net_profit_estimasi
        }
    }

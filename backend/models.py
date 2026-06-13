"""
SQLAlchemy ORM Models for MooOS — Koperasi Harapan Baru
"""
from sqlalchemy import (
    Column, Integer, Float, Text, ForeignKey, create_engine, event
)
from sqlalchemy.orm import (
    declarative_base, sessionmaker, scoped_session, relationship
)
import os

Base = declarative_base()

# ─── DATABASE ENGINE ─────────────────────────────────────────────
_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mooos.db")
engine = create_engine(
    f"sqlite:///{_DB_PATH}",
    connect_args={"check_same_thread": False},
    echo=False,
)

# Enable WAL mode for better concurrency
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()

# Thread-safe scoped session — one session per thread
SessionFactory = sessionmaker(bind=engine)
Session = scoped_session(SessionFactory)


def get_session():
    """Return the thread-local scoped session."""
    return Session()


# ─── MODELS ──────────────────────────────────────────────────────

class Member(Base):
    __tablename__ = "members"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False)
    nik = Column(Text)
    phone = Column(Text)
    alamat = Column(Text)
    role = Column(Text, default="Penitip Ternak")
    barn = Column(Text)
    iuran_wajib = Column(Float, default=200000.0)
    iuran_pokok = Column(Float, default=1500000.0)

    cows = relationship("Cow", back_populates="owner")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "nik": self.nik,
            "phone": self.phone,
            "alamat": self.alamat,
            "role": self.role,
            "barn": self.barn,
            "iuran_wajib": self.iuran_wajib or 200000.0,
            "iuran_pokok": self.iuran_pokok or 1500000.0,
        }


class Cow(Base):
    __tablename__ = "cows"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cow_code = Column(Text, unique=True)
    owner_id = Column(Integer, ForeignKey("members.id"))
    weight = Column(Float)
    status = Column(Text)
    caretaker = Column(Text)
    feed_qty_needed = Column(Float, default=0)
    barn = Column(Text)
    hash_id = Column(Text)
    jenis = Column(Text)
    umur = Column(Text)
    tgl_masuk = Column(Text)
    deskripsi = Column(Text)
    foto_path = Column(Text)
    lactate_status = Column(Text, default="Kering")
    litre_milked_today = Column(Float, default=0.0)

    owner = relationship("Member", back_populates="cows")

    def to_dict(self):
        return {
            "id": self.id,
            "cow_code": self.cow_code,
            "owner_id": self.owner_id,
            "owner_name": self.owner.name if self.owner else None,
            "weight": self.weight,
            "status": self.status,
            "caretaker": self.caretaker,
            "feed_qty_needed": self.feed_qty_needed,
            "barn": self.barn,
            "hash_id": self.hash_id,
            "jenis": self.jenis,
            "umur": self.umur,
            "tgl_masuk": self.tgl_masuk,
            "deskripsi": self.deskripsi,
            "foto_path": self.foto_path,
            "lactate_status": self.lactate_status,
            "litre_milked_today": self.litre_milked_today,
        }


class FeedOrder(Base):
    __tablename__ = "feed_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    po_code = Column(Text)
    qty = Column(Float)
    price_per_kg = Column(Float, default=5000)
    status = Column(Text)
    supplier = Column(Text)

    def to_dict(self):
        return {
            "id": self.id,
            "po_code": self.po_code,
            "qty": self.qty,
            "price_per_kg": self.price_per_kg or 5000,
            "status": self.status,
            "supplier": self.supplier,
        }


class FeedOrderRecipient(Base):
    __tablename__ = "feed_order_recipients"

    id = Column(Integer, primary_key=True, autoincrement=True)
    po_code = Column(Text)
    telegram_id = Column(Integer)


class MessageRef(Base):
    __tablename__ = "message_refs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ref_type = Column(Text)
    ref_id = Column(Text)
    chat_id = Column(Integer)
    message_id = Column(Integer)


class KoperasiConfig(Base):
    __tablename__ = "koperasi_config"

    key = Column(Text, primary_key=True)
    value = Column(Float)
    label = Column(Text)


class FeedFinancial(Base):
    __tablename__ = "feed_financials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Text, unique=True)
    total_kg = Column(Float)
    price_per_kg = Column(Float)
    estimated_cost = Column(Float)


class MilkFinancial(Base):
    __tablename__ = "milk_financials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Text, unique=True)
    total_liters = Column(Float)
    price_per_liter = Column(Float)
    estimated_revenue = Column(Float)


class WasteFinancial(Base):
    __tablename__ = "waste_financials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Text, unique=True)
    total_kg_fertilizer = Column(Float)
    price_per_kg = Column(Float)
    estimated_revenue = Column(Float)


class WasteProcessing(Base):
    __tablename__ = "waste_processing"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date_collected = Column(Text)
    kg_amount = Column(Float)
    status = Column(Text)
    ready_date = Column(Text)


class OperationalTransaction(Base):
    __tablename__ = "operational_transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Text)
    category = Column(Text)
    description = Column(Text)
    amount = Column(Float)
    type = Column(Text)


class FeedPriceHistory(Base):
    __tablename__ = "feed_price_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Text, unique=True)
    price_per_kg = Column(Float)


class DailyKandangLog(Base):
    __tablename__ = "daily_kandang_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Text)
    barn = Column(Text)
    type = Column(Text)  # 'PAKAN' or 'SUSU'
    telegram_id = Column(Integer)

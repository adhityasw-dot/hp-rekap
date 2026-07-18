from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    category: Mapped[str] = mapped_column(String(40), default="hp")  # hp, laptop, tablet, watch, accessory, service, other
    kind: Mapped[str] = mapped_column(String(20), default="unit")  # unit | bulk
    purchase_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    supplier: Mapped[str] = mapped_column(String(255), default="")
    buy_price: Mapped[float] = mapped_column(Float, default=0)  # total modal baris ini
    qty_total: Mapped[int] = mapped_column(Integer, default=1)
    qty_remaining: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="ready")  # ready | sold | partial
    sell_price: Mapped[float | None] = mapped_column(Float, nullable=True)  # total harga jual (unit) / kumulatif bulk
    sell_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    buyer: Mapped[str] = mapped_column(String(255), default="")  # nama pembeli
    buyer_phone: Mapped[str] = mapped_column(String(60), default="")  # WA / no HP pembeli
    notes: Mapped[str] = mapped_column(Text, default="")  # catatan terpisah dari pembeli
    # IMEI / serial (opsional)
    imei: Mapped[str] = mapped_column(String(32), default="", index=True)
    imei2: Mapped[str] = mapped_column(String(32), default="")
    meid: Mapped[str] = mapped_column(String(32), default="")
    serial_number: Mapped[str] = mapped_column(String(64), default="", index=True)
    battery_health: Mapped[str] = mapped_column(String(16), default="")  # mis. 89
    device_info_json: Mapped[str] = mapped_column(Text, default="")  # hasil cek IMEI (JSON)
    imei_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    imei_provider: Mapped[str] = mapped_column(String(80), default="")
    # Galeri foto unit + lampiran 3uTools (JSON list of {label, path, url})
    unit_photos_json: Mapped[str] = mapped_column(Text, default="[]")
    threetools_photos_json: Mapped[str] = mapped_column(Text, default="[]")
    source_month: Mapped[str] = mapped_column(String(40), default="")
    imported: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    costs: Mapped[list["ItemCost"]] = relationship(
        "ItemCost", back_populates="item", cascade="all, delete-orphan"
    )
    qc_checks: Mapped[list["ItemQcCheck"]] = relationship(
        "ItemQcCheck", back_populates="item", cascade="all, delete-orphan"
    )


class ItemQcCheck(Base):
    """Quality check per unit — template sama untuk beli & jual (phase hanya penanda)."""

    __tablename__ = "item_qc_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    phase: Mapped[str] = mapped_column(String(20), default="umum")  # beli | jual | umum
    contact_name: Mapped[str] = mapped_column(String(120), default="")
    contact_phone: Mapped[str] = mapped_column(String(60), default="")
    qc_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    answers_json: Mapped[str] = mapped_column(Text, default="{}")  # {key: ok|bad|percent, key_note: "..."}
    notes: Mapped[str] = mapped_column(Text, default="")
    photos_json: Mapped[str] = mapped_column(Text, default="[]")  # [{label, path, note}]
    cannot_check: Mapped[bool] = mapped_column(Boolean, default=False)
    cannot_check_reason: Mapped[str] = mapped_column(String(255), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    item: Mapped["Item"] = relationship("Item", back_populates="qc_checks")


class ItemCost(Base):
    __tablename__ = "item_costs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(120))
    amount: Mapped[float] = mapped_column(Float, default=0)
    cost_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    item: Mapped["Item"] = relationship("Item", back_populates="costs")


class CashEntry(Base):
    __tablename__ = "cash_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    txn_date: Mapped[date] = mapped_column(Date, index=True)
    direction: Mapped[str] = mapped_column(String(10))  # in | out
    entry_type: Mapped[str] = mapped_column(String(30))  # capital, purchase, sale, operational, withdraw, adjust
    amount: Mapped[float] = mapped_column(Float)  # always positive
    description: Mapped[str] = mapped_column(String(255), default="")
    ref_type: Mapped[str] = mapped_column(String(40), default="")  # item, operational, ...
    ref_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class OperationalExpense(Base):
    __tablename__ = "operational_expenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    expense_date: Mapped[date] = mapped_column(Date, index=True)
    category: Mapped[str] = mapped_column(String(80), default="umum")
    amount: Mapped[float] = mapped_column(Float, default=0)
    description: Mapped[str] = mapped_column(String(255), default="")
    cash_entry_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Partner(Base):
    """Partner bagi hasil (default 50:50 Adhit & Kamal)."""

    __tablename__ = "partners"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    share_percent: Mapped[float] = mapped_column(Float, default=50.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SaleNota(Base):
    """Arsip nota jual + TTD digital pembeli (hanya di website admin)."""

    __tablename__ = "sale_notas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    nota_no: Mapped[str] = mapped_column(String(32), index=True, default="")
    buyer_name: Mapped[str] = mapped_column(String(255), default="", index=True)
    buyer_phone: Mapped[str] = mapped_column(String(60), default="", index=True)
    item_name: Mapped[str] = mapped_column(String(255), default="")
    imei: Mapped[str] = mapped_column(String(32), default="")
    serial_number: Mapped[str] = mapped_column(String(64), default="")
    sell_price: Mapped[float] = mapped_column(Float, default=0)
    sell_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    battery_health: Mapped[str] = mapped_column(String(16), default="")
    # snapshot JSON untuk isi nota tetap (jika unit diedit nanti)
    snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    signature_path: Mapped[str] = mapped_column(String(512), default="")
    signed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    agreed_terms: Mapped[bool] = mapped_column(Boolean, default=False)
    voided: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

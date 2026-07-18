from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from .models import CashEntry, Item, ItemCost, OperationalExpense


def parse_money(value) -> float:
    """Parse Rupiah: Rp7.000.000 / Rp7,000,000 / 7000000."""
    import re

    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    raw = str(value).strip()
    if not raw:
        return 0.0
    raw = raw.replace("Rp", "").replace("rp", "").replace(" ", "")
    cleaned = re.sub(r"[^\d,.\-]", "", raw)
    if not cleaned or cleaned in ("-", ".", ",", "-.", "-,"):
        return 0.0

    if "," in cleaned and "." in cleaned:
        # Separator terakhir = desimal
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        parts = cleaned.split(",")
        # 7,000,000 → ribuan; 7,5 → desimal
        if len(parts) > 1 and all(len(p) == 3 for p in parts[1:]):
            cleaned = cleaned.replace(",", "")
        else:
            cleaned = cleaned.replace(",", ".")
    elif "." in cleaned:
        parts = cleaned.split(".")
        if len(parts) > 1 and all(len(p) == 3 for p in parts[1:]):
            cleaned = cleaned.replace(".", "")
        # else: desimal (7.5)

    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def parse_date(value, month_hint: int | None = None) -> Optional[date]:
    """Parse tanggal. month_hint (1-12) membantu bedakan d/m vs m/d."""
    import re

    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    s = str(value).strip().replace("//", "/")
    # typo sheet: 7/2.2026 → 7/2/2026
    s = re.sub(r"(\d{1,2})[/.-](\d{1,2})[.](\d{4})", r"\1/\2/\3", s)
    s = s.replace(".", "/") if re.match(r"^\d{1,2}/\d{1,2}\.\d{2,4}$", s) else s
    candidates: list[date] = []
    for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%d/%m/%y", "%m/%d/%y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            candidates.append(datetime.strptime(s, fmt).date())
        except ValueError:
            continue
    if not candidates:
        return None
    uniq: list[date] = []
    for c in candidates:
        if c not in uniq:
            uniq.append(c)
    if month_hint and 1 <= month_hint <= 12:
        preferred = [c for c in uniq if c.month == month_hint]
        if preferred:
            return preferred[0]
    return uniq[0]


BULAN_NAME = {
    1: "Januari",
    2: "Februari",
    3: "Maret",
    4: "April",
    5: "Mei",
    6: "Juni",
    7: "Juli",
    8: "Agustus",
    9: "September",
    10: "Oktober",
    11: "November",
    12: "Desember",
}


def sold_items_for_month(db: Session, year: int, month: int) -> list[Item]:
    """
    Item terjual untuk laporan bulanan.
    Utamakan source_month (sesuai tab sheet), fallback sell_date untuk input manual.
    """
    from sqlalchemy import or_, and_

    start, end = month_bounds(year, month)
    name = BULAN_NAME.get(month, "")
    q_sheet = (
        db.query(Item)
        .filter(
            Item.qty_remaining < Item.qty_total,
            Item.source_month.isnot(None),
            Item.source_month != "",
            Item.source_month.ilike(name),
        )
        .all()
    )
    q_manual = (
        db.query(Item)
        .filter(
            Item.sell_date.isnot(None),
            Item.sell_date >= start,
            Item.sell_date <= end,
            or_(Item.source_month.is_(None), Item.source_month == ""),
        )
        .all()
    )
    # dedupe by id
    seen = set()
    out: list[Item] = []
    for it in q_sheet + q_manual:
        if it.id not in seen:
            seen.add(it.id)
            out.append(it)
    out.sort(key=lambda x: (x.sell_date or date.min, x.id))
    return out


def profit_in_month(db: Session, year: int, month: int) -> float:
    total = 0.0
    for it in sold_items_for_month(db, year, month):
        p = item_profit(it)
        if p is not None:
            total += p
    return total


def revenue_in_month(db: Session, year: int, month: int) -> float:
    return sum((it.sell_price or 0) for it in sold_items_for_month(db, year, month))


def split_profit(amount: float, partners: list) -> list[tuple[str, float, float]]:
    """
    Bagi laba ke partner.
    partners: list of objects/dicts with .name and .share_percent
    Returns: [(name, percent, amount), ...]
    Sisa pembulatan ke partner terakhir.
    """
    if not partners:
        return []

    def _name(p):
        return p.name if hasattr(p, "name") else p.get("name", "")

    def _pct(p):
        if hasattr(p, "share_percent"):
            return float(p.share_percent or 0)
        return float(p.get("share_percent", 0) or 0)

    total_pct = sum(_pct(p) for p in partners)
    if total_pct <= 0:
        return []
    result = []
    allocated = 0.0
    for i, p in enumerate(partners):
        name = _name(p)
        pct = _pct(p)
        if i == len(partners) - 1:
            share_amt = round(amount - allocated)
        else:
            share_amt = round(amount * (pct / total_pct))
            allocated += share_amt
        result.append((name, pct, float(share_amt)))
    return result


def item_extra_costs(item: Item) -> float:
    return sum(c.amount for c in item.costs)


def item_cost_basis(item: Item) -> float:
    """Modal yang masih menempel di stok (proporsional qty remaining)."""
    if item.qty_total <= 0:
        return 0.0
    unit_buy = item.buy_price / item.qty_total
    return unit_buy * item.qty_remaining


def item_profit(item: Item) -> Optional[float]:
    if item.sell_price is None:
        return None
    sold_qty = item.qty_total - item.qty_remaining
    if item.kind == "unit":
        return (item.sell_price or 0) - item.buy_price - item_extra_costs(item)
    if sold_qty <= 0:
        return None
    # bulk: sell_price is cumulative revenue; cost = proportional buy + all costs
    cost = (item.buy_price / item.qty_total) * sold_qty + item_extra_costs(item)
    return (item.sell_price or 0) - cost


def cash_balance(db: Session) -> float:
    """Saldo buku kas penuh (semua cashflow historis)."""
    rows = db.query(CashEntry).all()
    bal = 0.0
    for r in rows:
        if r.direction == "in":
            bal += r.amount
        else:
            bal -= r.amount
    return bal


def modal_disetor(db: Session) -> float:
    """Total setor modal (entry_type capital, arah masuk)."""
    rows = (
        db.query(CashEntry)
        .filter(CashEntry.entry_type == "capital", CashEntry.direction == "in")
        .all()
    )
    return sum(r.amount for r in rows)


def kas_di_rekening(db: Session) -> float:
    """
    Estimasi uang di rekening ala spreadsheet:
    modal disetor − nilai modal yang masih mengendap di stok ready.
    (Bukan cashflow penuh yang menambahkan semua laba historis.)
    """
    return modal_disetor(db) - modal_in_goods(db)


def modal_in_goods(db: Session) -> float:
    items = db.query(Item).filter(Item.qty_remaining > 0).all()
    return sum(item_cost_basis(i) for i in items)


def ready_stock_breakdown(db: Session) -> dict:
    """Pisah stok ready: HP vs aksesoris vs lainnya."""
    items = db.query(Item).filter(Item.qty_remaining > 0).all()
    buckets = {
        "hp": {"count": 0, "qty": 0, "nilai": 0.0, "items": []},
        "aksesoris": {"count": 0, "qty": 0, "nilai": 0.0, "items": []},
        "lainnya": {"count": 0, "qty": 0, "nilai": 0.0, "items": []},
    }
    for it in items:
        cat = (it.category or "other").lower()
        if cat == "hp":
            key = "hp"
        elif cat == "accessory" or it.kind == "bulk":
            key = "aksesoris"
        else:
            key = "lainnya"  # laptop, tablet, watch, service, other
        buckets[key]["count"] += 1
        buckets[key]["qty"] += it.qty_remaining
        buckets[key]["nilai"] += item_cost_basis(it)
        buckets[key]["items"].append(it)
    return buckets


def add_cash(
    db: Session,
    *,
    txn_date: date,
    direction: str,
    entry_type: str,
    amount: float,
    description: str = "",
    ref_type: str = "",
    ref_id: Optional[int] = None,
    created_by: str = "",
) -> CashEntry:
    entry = CashEntry(
        txn_date=txn_date,
        direction=direction,
        entry_type=entry_type,
        amount=abs(float(amount)),
        description=description,
        ref_type=ref_type,
        ref_id=ref_id,
        created_by=created_by,
    )
    db.add(entry)
    return entry


def refresh_item_status(item: Item) -> None:
    if item.qty_remaining <= 0:
        item.status = "sold"
        item.qty_remaining = 0
    elif item.qty_remaining < item.qty_total:
        item.status = "partial"
    else:
        item.status = "ready"


def month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    return start, end


def profit_in_range(db: Session, start: date, end: date) -> float:
    items = (
        db.query(Item)
        .filter(Item.sell_date.isnot(None), Item.sell_date >= start, Item.sell_date <= end)
        .all()
    )
    total = 0.0
    for it in items:
        p = item_profit(it)
        if p is not None:
            total += p
    return total


def revenue_in_range(db: Session, start: date, end: date) -> float:
    items = (
        db.query(Item)
        .filter(Item.sell_date.isnot(None), Item.sell_date >= start, Item.sell_date <= end)
        .all()
    )
    return sum(it.sell_price or 0 for it in items)


def operational_in_range(db: Session, start: date, end: date) -> float:
    q = (
        db.query(func.coalesce(func.sum(OperationalExpense.amount), 0.0))
        .filter(
            OperationalExpense.expense_date >= start,
            OperationalExpense.expense_date <= end,
        )
        .scalar()
    )
    return float(q or 0)


def aging_days(item: Item, today: Optional[date] = None) -> Optional[int]:
    if not item.purchase_date or item.qty_remaining <= 0:
        return None
    today = today or date.today()
    return (today - item.purchase_date).days


def guess_category(name: str) -> str:
    n = (name or "").lower()
    if any(x in n for x in ("macbook", "laptop")):
        return "laptop"
    if "ipad" in n or "matepad" in n or "tablet" in n:
        return "tablet"
    if "watch" in n or "wacth" in n:
        return "watch"
    if any(
        x in n
        for x in (
            "charger",
            "kabel",
            "case",
            "temper",
            "softcase",
            "plastik",
            "kardus",
            "tg ",
        )
    ):
        return "accessory"
    if any(x in n for x in ("service", "servis", "battery", "baterai", "tembak imei", "lcd")):
        return "service"
    if any(x in n for x in ("iphone", "samsung", "huawei", "14 pro", "15 pro", "13 pro", "16 pro")):
        return "hp"
    return "other"


def guess_kind_and_qty(name: str, notes: str = "") -> tuple[str, int]:
    import re

    text = f"{name} {notes}"
    m = re.search(r"\((\d+)\s*pcs?\)", text, re.I)
    if m:
        return "bulk", int(m.group(1))
    m2 = re.search(r"(\d+)\s*pcs", text, re.I)
    if m2:
        return "bulk", int(m2.group(1))
    cat = guess_category(name)
    if cat == "accessory":
        return "bulk", 1
    return "unit", 1

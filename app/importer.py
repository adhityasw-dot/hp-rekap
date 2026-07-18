"""Import stok + penjualan/keuntungan dari Google Sheets HP Rekap."""

from __future__ import annotations

import csv
import io
import re
from datetime import date
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from . import services as svc
from .models import CashEntry, Item, ItemCost, OperationalExpense

SHEET_ID = "18LzVzlXT0EUOjrE8hb23mANjCiBJSSGzXc-hXB2W4Cw"


def parse_sheet_id(url_or_id: str) -> str:
    """Ambil ID spreadsheet dari link Google Sheets atau ID mentah."""
    s = (url_or_id or "").strip()
    if not s:
        return SHEET_ID
    # https://docs.google.com/spreadsheets/d/ID/...
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", s)
    if m:
        return m.group(1)
    # hanya ID
    if re.fullmatch(r"[a-zA-Z0-9-_]{20,}", s):
        return s
    return SHEET_ID

# gid tab penjualan per bulan (dari spreadsheet user)
SALES_GIDS: list[tuple[str, str]] = [
    ("Januari", "1746822674"),
    ("Februari", "1190503919"),
    ("Maret", "12197556"),
    ("April", "1800880785"),
    ("Mei", "1367378413"),
    ("Juni", "1070873381"),
    ("Juli", "146041437"),
]

STOCK_GID = "525762111"  # rekap stok (beli + checklist terjual)


def _norm_header(h: str) -> str:
    h = (h or "").strip().lower()
    h = h.replace("  ", " ")
    return h


def _header_map(headers: list[str]) -> dict[str, int]:
    """Map logical field -> column index."""
    idx: dict[str, int] = {}
    for i, h in enumerate(headers):
        n = _norm_header(h)
        if not n:
            continue
        if "tanggal" in n and "bayar" in n:
            idx["sell_date"] = i
        elif n.startswith("tanggal"):
            idx.setdefault("sell_date", i)
        elif "metode" in n:
            idx["method"] = i
        elif "pembeli" in n:
            idx["buyer"] = i
        elif "jenis" in n or n.strip() in ("barang", "barang "):
            idx["name"] = i
        elif "harga charger" in n or n == "charger":
            idx["charger"] = i
        elif "harga jual" in n:
            idx["sell"] = i
        elif "harga beli" in n:
            idx["buy"] = i
        elif "total keuntungan" in n:
            idx["profit"] = i
        elif n in ("keuntungan",) or (n.startswith("keuntungan") and "adhit" not in n and "kamal" not in n):
            idx.setdefault("profit", i)
        elif "keuntungan adhit" in n or n.endswith("adhit"):
            idx["share_adhit"] = i
        elif "keuntungan kamal" in n or n.endswith("kamal"):
            idx["share_kamal"] = i
        elif "biaya" in n:
            idx["extra"] = i
        elif "pembayaran" in n and "rekening" in n:
            idx["bank"] = i
        elif "catatan" in n or "keterangan" in n:
            idx["notes"] = i
    return idx


def _cell(row: list[str], idx: dict[str, int], key: str, default: str = "") -> str:
    i = idx.get(key)
    if i is None or i >= len(row):
        return default
    return (row[i] or "").strip()


def _is_skip_row(
    name: str,
    buy: float,
    sell: float,
    profit: float,
    *,
    buyer: str = "",
    method: str = "",
) -> bool:
    n = (name or "").strip().lower()
    if n in (
        "total",
        "jumlah",
        "kekurangan",
        "kelebihan",
        "summary",
        "adit",
        "adhit",
        "kamal",
    ):
        return True
    # Footer rekap (total omzet/laba bulanan) — tanpa identitas transaksi
    if not n:
        has_who = bool((buyer or "").strip() and buyer.strip() != "-") or bool(
            (method or "").strip()
        )
        # Penjualan kecil tanpa nama (charger Okto, dll.)
        if has_who and (sell > 0 or abs(profit) > 0):
            return False
        if not has_who:
            return True
        return True
    if buy <= 0 and sell <= 0 and abs(profit) == 0:
        return True
    return False


def fetch_csv(gid: str, sheet_id: str | None = None) -> str:
    sid = sheet_id or SHEET_ID
    url = f"https://docs.google.com/spreadsheets/d/{sid}/export?format=csv&gid={gid}"
    r = httpx.get(url, follow_redirects=True, timeout=45)
    r.raise_for_status()
    return r.text


_MONTH_NUM = {
    "januari": 1,
    "februari": 2,
    "maret": 3,
    "april": 4,
    "mei": 5,
    "juni": 6,
    "juli": 7,
    "agustus": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "desember": 12,
}


def month_num(label: str) -> int | None:
    return _MONTH_NUM.get((label or "").strip().lower())


def parse_sales_csv(content: str, month_label: str) -> list[dict]:
    if content.startswith("\ufeff"):
        content = content[1:]
    reader = csv.reader(io.StringIO(content))
    rows = list(reader)
    if not rows:
        return []

    headers = rows[0]
    idx = _header_map(headers)
    if "name" not in idx or "sell" not in idx:
        return []

    mhint = month_num(month_label)
    out: list[dict] = []
    for row in rows[1:]:
        if not row or all(not (c or "").strip() for c in row):
            continue
        while len(row) < len(headers):
            row.append("")

        name = _cell(row, idx, "name")
        buy = svc.parse_money(_cell(row, idx, "buy"))
        sell = svc.parse_money(_cell(row, idx, "sell"))
        profit_sheet = svc.parse_money(_cell(row, idx, "profit"))
        buyer = _cell(row, idx, "buyer")
        method = _cell(row, idx, "method")
        if _is_skip_row(
            name, buy, sell, profit_sheet, buyer=buyer, method=method
        ):
            continue

        charger = svc.parse_money(_cell(row, idx, "charger"))
        extra_raw = _cell(row, idx, "extra")
        extra_amt = svc.parse_money(extra_raw)
        # Jan sheet: "Biaya lain-lain" kadang teks "Charger"
        if extra_amt == 0 and extra_raw and not re.search(r"\d", extra_raw):
            extra_note = extra_raw
            extra_amt = 0.0
        else:
            extra_note = extra_raw if extra_amt != 0 else ""

        trailing = []
        max_i = max(idx.values(), default=0)
        for i, cell in enumerate(row):
            if i <= max_i:
                continue
            t = (cell or "").strip()
            if t and t not in trailing:
                trailing.append(t)

        raw_date = _cell(row, idx, "sell_date")
        sell_date = svc.parse_date(raw_date, month_hint=mhint)
        # Koreksi typo tahun di sheet (14/1/2027 → 2026)
        if sell_date and sell_date.year in (2027, 2028):
            try:
                sell_date = sell_date.replace(year=2026)
            except ValueError:
                pass
        # Jika tanggal gagal parse, pakai tgl 1 bulan sheet
        if not sell_date and mhint:
            sell_date = date(2026, mhint, 1)

        bank = _cell(row, idx, "bank")

        if not name:
            name = f"Aksesoris/lainnya ({buyer or method or 'tanpa nama'})"

        notes_parts = []
        if buyer and buyer != "-":
            notes_parts.append(f"Pembeli: {buyer}")
        if method:
            notes_parts.append(f"Metode: {method}")
        if bank:
            notes_parts.append(f"Rekening: {bank}")
        if extra_note and extra_amt == 0:
            notes_parts.append(f"Biaya: {extra_note}")
        if trailing:
            notes_parts.append(" | ".join(trailing[:3]))

        out.append(
            {
                "name": name,
                "buy": buy,
                "sell": sell,
                "charger": charger,
                "extra": abs(extra_amt) if extra_amt else 0.0,
                "sell_date": sell_date,
                "buyer": (buyer or "").strip() if (buyer or "").strip() not in ("-", "—") else "",
                "method": method or "",
                "notes": " · ".join(notes_parts),
                "month": month_label,
                "profit_sheet": profit_sheet,
            }
        )
    return out


def parse_stock_ready_csv(content: str) -> list[dict]:
    """Ambil hanya item yang belum terjual (Terjual=FALSE)."""
    if content.startswith("\ufeff"):
        content = content[1:]
    reader = csv.reader(io.StringIO(content))
    rows = list(reader)
    current_month = ""
    out: list[dict] = []

    def is_header(row: list[str]) -> bool:
        j = " ".join((c or "").lower() for c in row)
        return "waktu" in j and "barang" in j

    def month_from(row: list[str]) -> str:
        for c in row:
            t = (c or "").strip()
            if re.search(
                r"januari|februari|maret|april|mei|juni|juli|agustus|september|oktober|november|desember",
                t,
                re.I,
            ):
                return t
        return ""

    for row in rows:
        if not row or all(not (c or "").strip() for c in row):
            continue
        while len(row) < 7:
            row.append("")
        if is_header(row):
            current_month = month_from(row) or current_month
            continue

        joined = " ".join(row).lower()
        if "modal" in joined and not (row[2] or "").strip():
            continue
        if any(x in joined for x in ("sisa modal", "modal dalam")):
            continue
        if row[3] and "modal" in (row[3] or "").lower() and not (row[2] or "").strip():
            continue

        _, waktu, barang, tempat, harga, terjual, catatan = row[:7]
        barang = (barang or "").strip()
        if not barang:
            continue
        sold = (terjual or "").strip().upper() in (
            "TRUE",
            "1",
            "YES",
            "YA",
            "Y",
            "SOLD",
            "✓",
            "V",
        )
        if sold:
            continue  # sold diisi dari sheet penjualan

        price = svc.parse_money(harga)
        if price <= 0 and not waktu:
            continue
        kind, qty = svc.guess_kind_and_qty(barang, catatan or "")
        out.append(
            {
                "name": barang,
                "buy": price,
                "purchase_date": svc.parse_date(waktu),
                "supplier": (tempat or "").strip(),
                "notes": (catatan or "").strip(),
                "month": current_month,
                "kind": kind,
                "qty": qty,
            }
        )
    return out


def clear_business_data(db: Session) -> None:
    db.query(ItemCost).delete()
    db.query(Item).delete()
    db.query(CashEntry).delete()
    db.query(OperationalExpense).delete()
    db.flush()


def rebuild_cashflow(db: Session, *, capital: float, username: str) -> None:
    """Bangun ulang kas dari item: capital + penjualan − pembelian − biaya unit."""
    # hapus entri kas lama (kecuali kita sudah clear)
    items = db.query(Item).all()

    if capital > 0:
        # tanggal capital = penjualan pertama atau hari ini
        first_dates = [i.sell_date or i.purchase_date for i in items if (i.sell_date or i.purchase_date)]
        cap_date = min(first_dates) if first_dates else date.today()
        svc.add_cash(
            db,
            txn_date=cap_date,
            direction="in",
            entry_type="capital",
            amount=capital,
            description="Modal awal (import)",
            created_by=username,
        )

    for item in items:
        pdate = item.purchase_date or item.sell_date or date.today()
        if item.buy_price and item.buy_price > 0:
            svc.add_cash(
                db,
                txn_date=pdate,
                direction="out",
                entry_type="purchase",
                amount=item.buy_price,
                description=f"Beli: {item.name}",
                ref_type="item",
                ref_id=item.id,
                created_by=username,
            )
        for cost in item.costs:
            cdate = cost.cost_date or pdate
            if cost.amount > 0:
                svc.add_cash(
                    db,
                    txn_date=cdate,
                    direction="out",
                    entry_type="purchase",
                    amount=cost.amount,
                    description=f"{cost.label}: {item.name}",
                    ref_type="item",
                    ref_id=item.id,
                    created_by=username,
                )
        if item.sell_price and item.sell_price > 0 and item.qty_remaining < item.qty_total:
            sdate = item.sell_date or pdate
            svc.add_cash(
                db,
                txn_date=sdate,
                direction="in",
                entry_type="sale",
                amount=item.sell_price,
                description=f"Jual: {item.name}",
                ref_type="item",
                ref_id=item.id,
                created_by=username,
            )
    db.flush()


def import_full_from_google(
    db: Session,
    *,
    capital: float = 50_000_000,
    username: str = "admin",
    reset: bool = True,
    sheet_url: str = "",
) -> str:
    """Import stok ready + semua sheet penjualan Jan–Jul, bangun cashflow."""
    sid = parse_sheet_id(sheet_url)
    sales_by_month: list[tuple[str, list[dict]]] = []
    errors: list[str] = []

    for label, gid in SALES_GIDS:
        try:
            text = fetch_csv(gid, sid)
            rows = parse_sales_csv(text, label)
            sales_by_month.append((label, rows))
        except Exception as e:
            errors.append(f"{label}: {e}")

    try:
        stock_text = fetch_csv(STOCK_GID, sid)
        ready_rows = parse_stock_ready_csv(stock_text)
    except Exception as e:
        ready_rows = []
        errors.append(f"Stok: {e}")

    if reset:
        clear_business_data(db)

    sold_count = 0
    for label, rows in sales_by_month:
        for r in rows:
            item = Item(
                name=r["name"],
                category=svc.guess_category(r["name"]),
                kind="unit",
                purchase_date=None,
                supplier="",
                buy_price=r["buy"],
                qty_total=1,
                qty_remaining=0,
                status="sold",
                sell_price=r["sell"],
                sell_date=r["sell_date"],
                buyer=r.get("buyer") or "",
                notes=r["notes"],
                source_month=label,
                imported=True,
            )
            db.add(item)
            db.flush()
            if r["charger"] > 0:
                db.add(
                    ItemCost(
                        item_id=item.id,
                        label="Charger",
                        amount=r["charger"],
                        cost_date=r["sell_date"],
                    )
                )
            if r["extra"] > 0:
                db.add(
                    ItemCost(
                        item_id=item.id,
                        label="Biaya lain-lain",
                        amount=r["extra"],
                        cost_date=r["sell_date"],
                    )
                )
            sold_count += 1

    ready_count = 0
    for r in ready_rows:
        item = Item(
            name=r["name"],
            category=svc.guess_category(r["name"]),
            kind=r["kind"],
            purchase_date=r["purchase_date"],
            supplier=r["supplier"],
            buy_price=r["buy"],
            qty_total=r["qty"],
            qty_remaining=r["qty"],
            status="ready",
            sell_price=None,
            sell_date=None,
            notes=r["notes"],
            source_month=r["month"],
            imported=True,
        )
        db.add(item)
        ready_count += 1

    db.flush()
    rebuild_cashflow(db, capital=capital, username=username)
    db.commit()

    from sqlalchemy.orm import joinedload

    items = (
        db.query(Item)
        .options(joinedload(Item.costs))
        .filter(Item.status == "sold")
        .all()
    )
    profit_total = 0.0
    for it in items:
        p = svc.item_profit(it)
        if p is not None:
            profit_total += p

    kas = svc.cash_balance(db)
    modal = svc.modal_in_goods(db)
    by_month = ", ".join(f"{lab}={len(rows)}" for lab, rows in sales_by_month)

    def rp(n: float) -> str:
        return f"Rp{int(round(n)):,}".replace(",", ".")

    msg = (
        f"Import selesai. Penjualan: {sold_count} unit ({by_month}). "
        f"Stok ready: {ready_count}. "
        f"Total laba unit: {rp(profit_total)}. "
        f"Kas: {rp(kas)}. Modal di barang: {rp(modal)}."
    )
    if errors:
        msg += " Peringatan: " + "; ".join(errors)
    return msg


def import_sales_csv_file(db: Session, content: str, month_label: str, username: str) -> str:
    """Import satu file CSV penjualan (tanpa reset penuh)."""
    rows = parse_sales_csv(content, month_label)
    n = 0
    for r in rows:
        item = Item(
            name=r["name"],
            category=svc.guess_category(r["name"]),
            kind="unit",
            buy_price=r["buy"],
            qty_total=1,
            qty_remaining=0,
            status="sold",
            sell_price=r["sell"],
            sell_date=r["sell_date"],
            buyer=r.get("buyer") or "",
            notes=r["notes"],
            source_month=month_label,
            imported=True,
        )
        db.add(item)
        db.flush()
        if r["charger"] > 0:
            db.add(
                ItemCost(
                    item_id=item.id,
                    label="Charger",
                    amount=r["charger"],
                    cost_date=r["sell_date"],
                )
            )
        if r["extra"] > 0:
            db.add(
                ItemCost(
                    item_id=item.id,
                    label="Biaya lain-lain",
                    amount=r["extra"],
                    cost_date=r["sell_date"],
                )
            )
        # cash for this sale
        sdate = r["sell_date"] or date.today()
        if r["buy"] > 0:
            svc.add_cash(
                db,
                txn_date=sdate,
                direction="out",
                entry_type="purchase",
                amount=r["buy"],
                description=f"Beli: {item.name}",
                ref_type="item",
                ref_id=item.id,
                created_by=username,
            )
        for label, amt in (("Charger", r["charger"]), ("Biaya lain-lain", r["extra"])):
            if amt > 0:
                svc.add_cash(
                    db,
                    txn_date=sdate,
                    direction="out",
                    entry_type="purchase",
                    amount=amt,
                    description=f"{label}: {item.name}",
                    ref_type="item",
                    ref_id=item.id,
                    created_by=username,
                )
        if r["sell"] > 0:
            svc.add_cash(
                db,
                txn_date=sdate,
                direction="in",
                entry_type="sale",
                amount=r["sell"],
                description=f"Jual: {item.name}",
                ref_type="item",
                ref_id=item.id,
                created_by=username,
            )
        n += 1
    db.commit()
    return f"Import penjualan {month_label}: {n} unit."

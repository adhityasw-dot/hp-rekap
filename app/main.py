import csv
import io
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session

from .auth import (
    COOKIE_NAME,
    get_optional_user,
    hash_password,
    set_login_cookie,
    verify_password,
)
from .config import (  # noqa: F401
    ADMIN_DISPLAY,
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    CATALOG_TOKEN,
    DB_PATH,
    SHOP_AREA,
    SHOP_IG,
    SHOP_NAME,
    SHOP_TAGLINE,
    SHOP_TIKTOK,
    SHOP_WA,
)
from .database import Base, SessionLocal, engine, ensure_schema, get_db
from .models import (
    CashEntry,
    Item,
    ItemCost,
    ItemQcCheck,
    OperationalExpense,
    Partner,
    SaleNota,
    User,
)
from . import services as svc
from . import imei_service as imei_svc
from . import excel_export as xlsx
from .checklist_data import QC_TEMPLATE
import json
import secrets as secrets_mod

APP_DIR = Path(__file__).resolve().parent


def idr(value) -> str:
    try:
        n = float(value or 0)
    except (TypeError, ValueError):
        n = 0
    sign = "-" if n < 0 else ""
    n = abs(round(n))
    return f"{sign}Rp{n:,.0f}".replace(",", ".")


_jinja_env = Environment(
    loader=FileSystemLoader(str(APP_DIR / "templates")),
    autoescape=select_autoescape(["html", "xml"]),
    cache_size=0,
)
from markupsafe import Markup

_jinja_env.filters["idr"] = idr
_jinja_env.filters["tojson"] = lambda v: Markup(json.dumps(v, ensure_ascii=False))
templates = Jinja2Templates(env=_jinja_env)

app = FastAPI(title="Leks Phone")
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")

BULAN = {
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


def flash_redirect(url: str, ok: str = "", err: str = "") -> RedirectResponse:
    resp = RedirectResponse(url, status_code=303)
    if ok:
        resp.set_cookie("flash_ok", ok, max_age=8, httponly=False)
    if err:
        resp.set_cookie("flash_err", err, max_age=8, httponly=False)
    return resp


def pop_flash(request: Request, response_headers_holder: dict | None = None):
    ok = request.cookies.get("flash_ok")
    err = request.cookies.get("flash_err")
    return ok, err


def render(request: Request, name: str, ctx: dict, user=None):
    ok = request.cookies.get("flash_ok")
    err = request.cookies.get("flash_err")
    context = {
        "user": user,
        "flash_ok": ok,
        "flash_err": err,
    }
    context.update(ctx)
    response = templates.TemplateResponse(
        request=request,
        name=name,
        context=context,
    )
    if ok:
        response.delete_cookie("flash_ok")
    if err:
        response.delete_cookie("flash_err")
    return response


def require_user(request: Request, db: Session) -> User | RedirectResponse:
    user = get_optional_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return user


def seed_if_needed():
    """Pastikan 1 user admin = ADMIN_USERNAME / ADMIN_PASSWORD dari Railway."""
    Base.metadata.create_all(bind=engine)
    ensure_schema()
    db = SessionLocal()
    try:
        db.query(User).delete()
        db.add(
            User(
                username=ADMIN_USERNAME,
                password_hash=hash_password(ADMIN_PASSWORD),
                display_name=ADMIN_DISPLAY,
            )
        )
        if db.query(Partner).count() == 0:
            db.add(Partner(name="Adhit", share_percent=50.0, sort_order=1, active=True))
            db.add(Partner(name="Kamal", share_percent=50.0, sort_order=2, active=True))
        db.commit()
    except Exception:
        db.rollback()
        # Jangan crash app — login bisa tetap pakai env langsung
    finally:
        db.close()


def active_partners(db: Session) -> list[Partner]:
    return (
        db.query(Partner)
        .filter(Partner.active.is_(True))
        .order_by(Partner.sort_order, Partner.id)
        .all()
    )


@app.on_event("startup")
def on_startup():
    try:
        seed_if_needed()
    except Exception:
        pass


# ---------- Auth ----------
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    user = get_optional_user(request, db)
    if user:
        return RedirectResponse("/", status_code=303)
    return render(request, "login.html", {}, user=None)


@app.post("/login")
def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    uname = (username or "").strip()
    pwd = (password or "").strip()

    # === LOGIN LANGSUNG DARI VARIABLES (paling andal) ===
    # Tidak bergantung hash DB yang bisa mismatch
    if uname == ADMIN_USERNAME and pwd == ADMIN_PASSWORD:
        try:
            seed_if_needed()
        except Exception:
            pass
        resp = RedirectResponse("/", status_code=303)
        set_login_cookie(resp, ADMIN_USERNAME)
        return resp

    # Fallback: cek hash di database
    try:
        seed_if_needed()
        db.expire_all()
        user = db.query(User).filter(User.username == uname).first()
        if user and verify_password(pwd, user.password_hash):
            resp = RedirectResponse("/", status_code=303)
            set_login_cookie(resp, user.username)
            return resp
    except Exception:
        pass

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "user": None,
            "flash_ok": None,
            "flash_err": (
                f"Login gagal. Username env={ADMIN_USERNAME!r}. "
                f"Pastikan sama dengan Railway Variables ADMIN_USERNAME / ADMIN_PASSWORD. "
                f"Kode GitHub harus sudah di-update (commit terbaru)."
            ),
        },
    )


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(COOKIE_NAME)
    return resp


# ---------- Dashboard ----------
@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = get_optional_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    today = date.today()
    year, month = today.year, today.month
    start, end = svc.month_bounds(year, month)
    bulan_label = BULAN.get(month, "")
    # Kas di rekening = modal disetor − stok (pola spreadsheet), bukan cashflow penuh
    kas_rekening = svc.kas_di_rekening(db)
    modal_setor = svc.modal_disetor(db)
    modal_barang = svc.modal_in_goods(db)
    # Omzet/laba/ops hanya bulan kalender berjalan (real-time)
    laba_bulan = svc.profit_in_month(db, year, month)
    omzet_bulan = svc.revenue_in_month(db, year, month)
    ops_bulan = svc.operational_in_range(db, start, end)
    partners = active_partners(db)
    bagi_hasil = svc.split_profit(laba_bulan, partners)
    ready_break = svc.ready_stock_breakdown(db)
    ready = db.query(Item).filter(Item.qty_remaining > 0).all()
    aging_threshold = 14
    aging = []
    for it in ready:
        d = svc.aging_days(it, today)
        if d is not None and d >= aging_threshold:
            aging.append((it, d))
    aging.sort(key=lambda x: x[1], reverse=True)
    recent_cash = (
        db.query(CashEntry).order_by(CashEntry.txn_date.desc(), CashEntry.id.desc()).limit(8).all()
    )
    return render(
        request,
        "dashboard.html",
        {
            "kas_rekening": kas_rekening,
            "modal_setor": modal_setor,
            "modal_barang": modal_barang,
            "laba_bulan": laba_bulan,
            "omzet_bulan": omzet_bulan,
            "ops_bulan": ops_bulan,
            "bagi_hasil": bagi_hasil,
            # flat keys — hindari bentrok Jinja dict.items
            "ready_hp_count": ready_break["hp"]["count"],
            "ready_hp_qty": ready_break["hp"]["qty"],
            "ready_hp_nilai": ready_break["hp"]["nilai"],
            "ready_hp_items": ready_break["hp"]["items"],
            "ready_aks_count": ready_break["aksesoris"]["count"],
            "ready_aks_qty": ready_break["aksesoris"]["qty"],
            "ready_aks_nilai": ready_break["aksesoris"]["nilai"],
            "ready_aks_items": ready_break["aksesoris"]["items"],
            "ready_lain_count": ready_break["lainnya"]["count"],
            "ready_lain_qty": ready_break["lainnya"]["qty"],
            "ready_lain_nilai": ready_break["lainnya"]["nilai"],
            "ready_lain_items": ready_break["lainnya"]["items"],
            "ready_count": len(ready),
            "aging": aging[:10],
            "aging_threshold": aging_threshold,
            "recent_cash": recent_cash,
            "bulan_label": bulan_label,
            "tahun_label": year,
            "today": today,
        },
        user=user,
    )


def _parse_qc_answers(answers_json: str | None) -> dict:
    try:
        ans = json.loads(answers_json or "{}")
    except Exception:
        ans = {}
    return ans if isinstance(ans, dict) else {}


def _qc_counts(answers: dict) -> tuple[int, int]:
    """Hitung OK / bermasalah (abaikan key_note & percent non ok/bad)."""
    ok_n = sum(1 for k, v in answers.items() if v == "ok" and not str(k).endswith("_note"))
    bad_n = sum(1 for k, v in answers.items() if v == "bad" and not str(k).endswith("_note"))
    return ok_n, bad_n


def _qc_meta_map(db: Session, item_ids: list[int]) -> dict[int, dict]:
    """Ringkasan QC per item: prioritaskan phase beli, lalu QC terbaru."""
    if not item_ids:
        return {}
    rows = (
        db.query(ItemQcCheck)
        .filter(ItemQcCheck.item_id.in_(item_ids))
        .order_by(ItemQcCheck.created_at.desc())
        .all()
    )
    newest: dict[int, dict] = {}
    buy_map: dict[int, dict] = {}
    for qc in rows:
        answers = _parse_qc_answers(qc.answers_json)
        ok_n, bad_n = _qc_counts(answers)
        entry = {
            "phase": qc.phase,
            "ok": ok_n,
            "bad": bad_n,
            "has_qc": True,
            "cannot_check": bool(qc.cannot_check),
            "qc_id": qc.id,
        }
        if qc.item_id not in newest:
            newest[qc.item_id] = entry
        if qc.phase == "beli" and qc.item_id not in buy_map:
            buy_map[qc.item_id] = entry

    meta: dict[int, dict] = {}
    for iid in item_ids:
        buy = buy_map.get(iid) or newest.get(iid)
        if not buy:
            continue
        m = {
            "has_qc": True,
            "buy": buy,
            "ok": buy["ok"],
            "bad": buy["bad"],
            "cannot_check": buy["cannot_check"],
            "phase": buy["phase"],
        }
        if buy.get("cannot_check"):
            m["badge"] = "none"
            m["badge_label"] = "QC skip"
        elif buy.get("bad", 0) > 0:
            m["badge"] = "bad"
            m["badge_label"] = f"QC {buy['bad']} bermasalah"
        elif buy.get("ok", 0) > 0:
            m["badge"] = "ok"
            m["badge_label"] = "QC OK"
        else:
            m["badge"] = "partial"
            m["badge_label"] = "QC kosong"
        meta[iid] = m
    return meta


# ---------- Stok ----------
@app.get("/stok", response_class=HTMLResponse)
def stok(
    request: Request,
    q: str = "",
    status: str = "ready",
    category: str = "",
    db: Session = Depends(get_db),
):
    user = get_optional_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    query = db.query(Item)
    if status == "ready":
        query = query.filter(Item.qty_remaining > 0)
    elif status == "sold":
        query = query.filter(Item.qty_remaining <= 0)
    if category:
        query = query.filter(Item.category == category)
    if q.strip():
        term = q.strip()
        like = f"%{term}%"
        digits = re.sub(r"\D", "", term)
        dig_like = f"%{digits}%" if digits else like
        query = query.filter(
            Item.name.ilike(like)
            | Item.supplier.ilike(like)
            | Item.imei.ilike(like)
            | Item.imei.ilike(dig_like)
            | Item.imei2.ilike(like)
            | Item.imei2.ilike(dig_like)
            | Item.serial_number.ilike(like)
            | Item.buyer.ilike(like)
        )
    items = query.order_by(Item.purchase_date.desc(), Item.id.desc()).all()
    categories = [r[0] for r in db.query(Item.category).distinct().all() if r[0]]
    qc_meta = _qc_meta_map(db, [it.id for it in items])
    return render(
        request,
        "stok.html",
        {
            "items": items,
            "q": q,
            "status": status,
            "category": category,
            "categories": categories,
            "qc_meta": qc_meta,
        },
        user=user,
    )


# ---------- Beli ----------
@app.get("/beli", response_class=HTMLResponse)
def beli_form(request: Request, db: Session = Depends(get_db)):
    user = get_optional_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    groups: dict[str, list] = {}
    for row in QC_TEMPLATE:
        groups.setdefault(row["group"], []).append(row)
    return render(
        request,
        "beli.html",
        {"today": date.today().isoformat(), "qc_groups": groups},
        user=user,
    )


def _qc_answers_from_form(form) -> dict:
    """Parse QC: ok/bad (+ note jika bad), percent. Tanpa N/A."""
    answers: dict = {}
    for row in QC_TEMPLATE:
        key = row["key"]
        if row["type"] == "percent":
            val = str(form.get(f"qc_{key}") or "").strip()
            if val:
                answers[key] = val
        else:
            val = str(form.get(f"qc_{key}") or "").strip()
            if val in ("ok", "bad"):
                answers[key] = val
                if val == "bad":
                    note = str(form.get(f"qc_{key}_note") or "").strip()
                    if note:
                        answers[f"{key}_note"] = note
    return answers


async def _collect_upload_bytes(form, field_name: str = "screenshot") -> list[bytes]:
    """Ambil 1 atau banyak file upload (getlist)."""
    files: list[bytes] = []
    items = []
    if hasattr(form, "getlist"):
        items = form.getlist(field_name)
    else:
        one = form.get(field_name)
        if one:
            items = [one]
    for up in items:
        if up and hasattr(up, "read"):
            data = await up.read()
            if data and len(data) <= 12 * 1024 * 1024:
                files.append(data)
    return files


async def _save_qc_photos(form, item_id: int) -> list[dict]:
    """Foto lampiran masalah QC: qc_photo file + qc_photo_label text (parallel lists)."""
    return await _save_upload_field(
        form,
        file_field="qc_photo",
        label_field="qc_photo_label",
        item_id=item_id,
        default_label="Foto masalah",
        subdir_prefix="qc",
    )


async def _save_upload_field(
    form,
    *,
    file_field: str,
    item_id: int,
    label_field: str | None = None,
    default_label: str = "Foto",
    subdir_prefix: str = "misc",
    max_files: int = 20,
) -> list[dict]:
    """Simpan multi-upload (getlist). Return [{label, path, url}]."""
    from . import media as media_svc

    photos: list[dict] = []
    labels: list = []
    files: list = []
    if hasattr(form, "getlist"):
        files = form.getlist(file_field) or []
        if label_field:
            labels = form.getlist(label_field) or []
    if not files and form.get(file_field):
        files = [form.get(file_field)]
        if label_field:
            labels = [form.get(label_field) or ""]
    n = 0
    for i, up in enumerate(files):
        if n >= max_files:
            break
        if not up or not hasattr(up, "read"):
            continue
        data = await up.read()
        if not data:
            continue
        if len(data) > 12 * 1024 * 1024:
            continue
        fname = getattr(up, "filename", "") or "foto.jpg"
        rel = media_svc.save_upload(
            data, fname, subdir=f"{item_id}/{subdir_prefix}"
        )
        if not rel:
            continue
        lab = ""
        if i < len(labels):
            lab = str(labels[i] or "").strip()
        n += 1
        urls = media_svc.media_urls(rel)
        photos.append(
            {
                "label": lab or f"{default_label} {n}",
                "path": rel,
                "url": urls["url"],
                "thumb_url": urls["thumb_url"],
            }
        )
    return photos


def _parse_photos_json(raw: str | None) -> list[dict]:
    """Parse JSON foto + pastikan thumb ada (generate on-demand untuk foto lama)."""
    from . import media as media_svc

    try:
        data = json.loads(raw or "[]")
    except Exception:
        data = []
    if not isinstance(data, list):
        return []
    out = []
    for p in data:
        if not isinstance(p, dict):
            continue
        path = (p.get("path") or "").replace("\\", "/")
        url = p.get("url") or ""
        if path:
            urls = media_svc.media_urls(path, ensure=True)
            url = urls["url"]
            thumb = urls["thumb_url"]
        else:
            if not url:
                continue
            thumb = p.get("thumb_url") or url
        out.append(
            {
                "label": p.get("label") or "Foto",
                "path": path,
                "url": url,
                "thumb_url": thumb,
            }
        )
    return out


@app.post("/beli")
async def beli_post(
    request: Request,
    db: Session = Depends(get_db),
):
    user = get_optional_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    form = await request.form()
    name = str(form.get("name") or "").strip()
    if not name:
        return flash_redirect("/beli", err="Nama barang wajib diisi.")

    try:
        qty = max(1, int(str(form.get("qty") or "1")))
    except ValueError:
        qty = 1
    price = svc.parse_money(form.get("buy_price"))
    pdate = svc.parse_date(form.get("purchase_date")) or date.today()
    category = str(form.get("category") or "hp")
    kind = str(form.get("kind") or "unit")
    if kind not in ("unit", "bulk"):
        kind = "unit"

    imei = imei_svc.clean_imei(str(form.get("imei") or ""))
    imei2 = imei_svc.clean_imei(str(form.get("imei2") or ""))
    meid = str(form.get("meid") or "").strip()
    serial = imei_svc.clean_serial(str(form.get("serial_number") or ""))
    battery = str(form.get("qc_battery_health") or form.get("battery_health") or "").strip()
    answers = _qc_answers_from_form(form)
    if answers.get("battery_health"):
        battery = str(answers["battery_health"])

    # Info perangkat dari OCR (hidden JSON) atau field form / upload langsung
    device_info: dict = {}
    raw_json = str(form.get("device_info_json") or "").strip()
    if raw_json:
        try:
            device_info = json.loads(raw_json)
            if not isinstance(device_info, dict):
                device_info = {}
        except Exception:
            device_info = {}
    # field form info (manual/OCR-filled)
    form_dict = {k: str(form.get(k) or "") for k in form.keys()}
    manual = imei_svc.build_manual_info(form_dict)
    if manual:
        device_info = {**device_info, **manual}

    # optional: multi screenshot ikut di form simpan
    try:
        shots = await _collect_upload_bytes(form, "screenshot")
        if shots:
            from . import ocr_service as ocr

            _ok, info, _txt, _msg = ocr.process_screenshots(shots)
            if info:
                device_info = {
                    **device_info,
                    **{k: v for k, v in info.items() if not str(k).startswith("_") or k == "_ocr_preview"},
                }
                device_info["_provider"] = "screenshot_ocr"
                if info.get("imei") and not imei:
                    imei = imei_svc.clean_imei(str(info["imei"]))
                if info.get("imei2") and not imei2:
                    imei2 = imei_svc.clean_imei(str(info["imei2"]))
                if info.get("serial") and not serial:
                    serial = imei_svc.clean_serial(str(info["serial"]))
    except Exception:
        pass

    item = Item(
        name=name,
        category=category,
        kind=kind,
        purchase_date=pdate,
        supplier=str(form.get("supplier") or "").strip(),
        buy_price=price,
        qty_total=qty,
        qty_remaining=qty,
        status="ready",
        notes=str(form.get("notes") or "").strip(),
        imei=imei,
        imei2=imei2,
        meid=meid,
        serial_number=serial,
        battery_health=battery,
    )
    if device_info:
        if imei:
            device_info["imei"] = imei
        if imei2:
            device_info["imei2"] = imei2
        if serial:
            device_info["serial"] = serial
        _apply_device_info_to_item(item, device_info)
        # jangan timpa nama barang yang user isi
        item.name = name
        item.imei = imei or item.imei
        item.serial_number = serial or item.serial_number
    db.add(item)
    db.flush()
    svc.add_cash(
        db,
        txn_date=pdate,
        direction="out",
        entry_type="purchase",
        amount=price,
        description=f"Beli: {item.name}",
        ref_type="item",
        ref_id=item.id,
        created_by=user.username,
    )

    # Foto unit + 3uTools (multi)
    unit_photos = await _save_upload_field(
        form,
        file_field="unit_photo",
        item_id=item.id,
        default_label="Foto unit",
        subdir_prefix="unit",
    )
    threetools_photos = await _save_upload_field(
        form,
        file_field="threetools_photo",
        item_id=item.id,
        default_label="3uTools",
        subdir_prefix="3utools",
    )
    item.unit_photos_json = json.dumps(unit_photos, ensure_ascii=False)
    item.threetools_photos_json = json.dumps(threetools_photos, ensure_ascii=False)

    cannot = form.get("cannot_check") in ("1", "on", "true", "True")
    photos = await _save_qc_photos(form, item.id)
    qc = ItemQcCheck(
        item_id=item.id,
        phase="beli",
        contact_name=str(form.get("contact_name") or "").strip(),
        contact_phone=str(form.get("contact_phone") or "").strip(),
        qc_date=pdate,
        answers_json=json.dumps(answers, ensure_ascii=False),
        notes=str(form.get("qc_notes") or "").strip(),
        photos_json=json.dumps(photos, ensure_ascii=False),
        cannot_check=cannot,
        cannot_check_reason=str(form.get("cannot_check_reason") or "").strip(),
        created_by=user.username,
    )
    db.add(qc)
    db.commit()

    total_pts = len(QC_TEMPLATE)
    done = len(answers)
    bad = sum(1 for v in answers.values() if v == "bad")
    pending = 0 if cannot else max(0, total_pts - done)
    extra = ""
    if cannot:
        extra = " QC di-skip (tidak bisa dicek fungsional)."
    elif pending or bad:
        extra = f" QC: {done}/{total_pts} dicek"
        if pending:
            extra += f", {pending} belum"
        if bad:
            extra += f", {bad} bermasalah"
        extra += "."
    else:
        extra = f" QC lengkap ({done}/{total_pts})."

    return flash_redirect(
        f"/item/{item.id}",
        ok=f"Pembelian tersimpan: {item.name}.{extra}",
    )


# ---------- Jual ----------
@app.get("/jual", response_class=HTMLResponse)
def jual_form(
    request: Request,
    item_id: int | None = None,
    db: Session = Depends(get_db),
):
    user = get_optional_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    ready_items = (
        db.query(Item)
        .filter(Item.qty_remaining > 0)
        .order_by(Item.purchase_date.desc())
        .all()
    )
    preselect_id = item_id if item_id and any(it.id == item_id for it in ready_items) else None
    qc_meta = _qc_meta_map(db, [it.id for it in ready_items])
    groups: dict[str, list] = {}
    for row in QC_TEMPLATE:
        groups.setdefault(row["group"], []).append(row)
    # JSON ringkas untuk preview soft-warning di client
    items_json = []
    for it in ready_items:
        m = qc_meta.get(it.id) or {}
        buy = m.get("buy") or {}
        items_json.append(
            {
                "id": it.id,
                "name": it.name,
                "buy": it.buy_price,
                "imei": it.imei or "",
                "serial": it.serial_number or "",
                "has_qc": bool(m.get("has_qc")),
                "qc_bad": int(buy.get("bad") or 0),
                "qc_ok": int(buy.get("ok") or 0),
                "qc_badge": m.get("badge") or "none",
                "qc_label": m.get("badge_label") or "Belum QC beli",
            }
        )
    return render(
        request,
        "jual.html",
        {
            "today": date.today().isoformat(),
            "ready_items": ready_items,
            "qc_meta": qc_meta,
            "qc_groups": groups,
            "items_json": items_json,
            "preselect_id": preselect_id,
        },
        user=user,
    )


def _parse_cost_rows(form) -> list[tuple[str, float]]:
    """Ambil pasangan (label, amount) dari form multi-value cost_label / cost_amount."""
    labels = form.getlist("cost_label") if hasattr(form, "getlist") else []
    amounts = form.getlist("cost_amount") if hasattr(form, "getlist") else []
    # starlette FormData getlist
    if not labels and "cost_label" in form:
        raw_l = form.get("cost_label")
        labels = [raw_l] if raw_l is not None else []
    if not amounts and "cost_amount" in form:
        raw_a = form.get("cost_amount")
        amounts = [raw_a] if raw_a is not None else []

    rows: list[tuple[str, float]] = []
    n = max(len(labels), len(amounts))
    for i in range(n):
        label = (labels[i] if i < len(labels) else "") or ""
        label = str(label).strip()
        amt = svc.parse_money(amounts[i] if i < len(amounts) else 0)
        if amt == 0 and not label:
            continue
        if amt == 0:
            continue
        if not label:
            label = "Biaya lain-lain"
        rows.append((label, abs(amt)))
    return rows


@app.post("/jual")
async def jual_post(
    request: Request,
    db: Session = Depends(get_db),
):
    user = get_optional_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    form = await request.form()
    try:
        item_id = int(str(form.get("item_id") or "0"))
    except ValueError:
        return flash_redirect("/jual", err="Item tidak valid.")

    item = db.query(Item).filter(Item.id == item_id).first()
    if not item or item.qty_remaining <= 0:
        return flash_redirect("/jual", err="Item tidak tersedia.")

    try:
        qty = max(1, min(int(str(form.get("qty") or "1")), item.qty_remaining))
    except ValueError:
        qty = 1

    price = svc.parse_money(form.get("sell_price"))
    sdate = svc.parse_date(form.get("sell_date")) or date.today()
    buyer = str(form.get("buyer") or "").strip()
    buyer_phone = str(form.get("buyer_phone") or form.get("contact_phone") or "").strip()
    notes = str(form.get("notes") or "").strip()
    charger = svc.parse_money(form.get("charger_price"))
    # Default: biaya hanya potong laba unit; kas opsional
    costs_affect_cash = form.get("costs_affect_cash") in ("1", "on", "true", "True")
    extra_costs = _parse_cost_rows(form)

    item.qty_remaining -= qty
    if item.sell_price is None:
        item.sell_price = price
    else:
        item.sell_price = (item.sell_price or 0) + price
    item.sell_date = sdate
    if buyer:
        item.buyer = buyer
    if buyer_phone:
        item.buyer_phone = buyer_phone
    if notes:
        item.notes = notes if not item.notes else (item.notes + " | " + notes)
    svc.refresh_item_status(item)
    db.flush()

    # Biaya menempel di unit ini → item_profit = jual − modal − sum(costs)
    cost_entries: list[tuple[str, float]] = []
    if charger > 0:
        cost_entries.append(("Charger", charger))
    cost_entries.extend(extra_costs)

    total_extra = 0.0
    for label, amt in cost_entries:
        db.add(
            ItemCost(
                item_id=item.id,
                label=label,
                amount=amt,
                cost_date=sdate,
                notes="potong laba unit saat jual",
            )
        )
        total_extra += amt
        if costs_affect_cash:
            svc.add_cash(
                db,
                txn_date=sdate,
                direction="out",
                entry_type="purchase",
                amount=amt,
                description=f"{label}: {item.name}",
                ref_type="item",
                ref_id=item.id,
                created_by=user.username,
            )

    svc.add_cash(
        db,
        txn_date=sdate,
        direction="in",
        entry_type="sale",
        amount=price,
        description=f"Jual: {item.name}"
        + (f" x{qty}" if qty > 1 else "")
        + (f" · {buyer}" if buyer else ""),
        ref_type="item",
        ref_id=item.id,
        created_by=user.username,
    )

    # QC jual opsional (soft skip) — simpan jika ada isian / cannot_check / no. HP nota
    answers = _qc_answers_from_form(form)
    cannot = form.get("cannot_check") in ("1", "on", "true", "True")
    if answers.get("battery_health"):
        item.battery_health = str(answers["battery_health"])
    if answers or cannot or buyer_phone:
        photos = await _save_qc_photos(form, item.id) if (answers or cannot) else []
        qc = ItemQcCheck(
            item_id=item.id,
            phase="jual",
            contact_name=buyer or str(form.get("contact_name") or "").strip(),
            contact_phone=buyer_phone or str(form.get("contact_phone") or "").strip(),
            qc_date=sdate,
            answers_json=json.dumps(answers, ensure_ascii=False),
            notes=str(form.get("qc_notes") or "").strip(),
            photos_json=json.dumps(photos, ensure_ascii=False),
            cannot_check=cannot,
            cannot_check_reason=str(form.get("cannot_check_reason") or "").strip(),
            created_by=user.username,
        )
        db.add(qc)

    db.commit()

    # Laba unit setelah biaya
    db.refresh(item)
    profit = svc.item_profit(item)
    msg = "Penjualan tersimpan."
    if total_extra > 0:
        msg += f" Biaya {idr(total_extra)} dipotong dari laba unit ini."
    if profit is not None:
        msg += f" Laba unit: {idr(profit)}."
    # redirect ke nota jual (printable)
    return flash_redirect(f"/item/{item.id}/nota", ok=msg)


# ---------- Nota jual + TTD digital + arsip ----------
def _nota_shop() -> dict:
    return {
        "address": "Karanganyar",
        "wa": "0856-4737-7078",
        "ig": "@aadhitsatriaa",
        "tiktok": "@aadhitsatriaa",
        "slogan": "Melayani Sepenuh Hati",
        "seller_name": "Adhit",
    }


def _ensure_sale_nota(db: Session, item: Item, user_name: str = "") -> SaleNota:
    """Buat / ambil arsip nota untuk unit terjual."""
    nota = (
        db.query(SaleNota)
        .filter(SaleNota.item_id == item.id, SaleNota.voided == False)  # noqa: E712
        .order_by(SaleNota.id.desc())
        .first()
    )
    buyer_phone = _extract_phone_from_item(item, db)
    nota_no = f"LP-{item.id:05d}"
    sdate = item.sell_date
    if sdate:
        sell_date_label = f"{sdate.day} {BULAN.get(sdate.month, '')} {sdate.year}"
    else:
        sell_date_label = "—"

    snapshot = {
        "nota_no": nota_no,
        "buyer": item.buyer or "",
        "buyer_phone": buyer_phone,
        "item_name": item.name,
        "imei": item.imei or "",
        "imei2": item.imei2 or "",
        "serial": item.serial_number or "",
        "battery": item.battery_health or "",
        "sell_price": item.sell_price or 0,
        "sell_date": item.sell_date.isoformat() if item.sell_date else "",
        "sell_date_label": sell_date_label,
        "shop": _nota_shop(),
    }

    if nota:
        # update metadata live (kecuali sudah signed — snapshot tetap)
        if not nota.signature_path:
            nota.buyer_name = item.buyer or nota.buyer_name
            nota.buyer_phone = buyer_phone or nota.buyer_phone
            nota.item_name = item.name
            nota.imei = item.imei or ""
            nota.serial_number = item.serial_number or ""
            nota.sell_price = float(item.sell_price or 0)
            nota.sell_date = item.sell_date
            nota.battery_health = item.battery_health or ""
            nota.snapshot_json = json.dumps(snapshot, ensure_ascii=False)
        return nota

    nota = SaleNota(
        item_id=item.id,
        nota_no=nota_no,
        buyer_name=item.buyer or "",
        buyer_phone=buyer_phone,
        item_name=item.name,
        imei=item.imei or "",
        serial_number=item.serial_number or "",
        sell_price=float(item.sell_price or 0),
        sell_date=item.sell_date,
        battery_health=item.battery_health or "",
        snapshot_json=json.dumps(snapshot, ensure_ascii=False),
        created_by=user_name,
    )
    db.add(nota)
    db.flush()
    return nota


@app.get("/item/{item_id}/nota", response_class=HTMLResponse)
def item_nota(request: Request, item_id: int, db: Session = Depends(get_db)):
    user = get_optional_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        return flash_redirect("/stok", err="Item tidak ditemukan.")
    if not item.sell_date and item.sell_price is None:
        return flash_redirect(f"/item/{item.id}", err="Belum ada penjualan untuk unit ini.")

    nota = _ensure_sale_nota(db, item, user.username)
    db.commit()
    db.refresh(nota)

    buyer_phone = nota.buyer_phone or _extract_phone_from_item(item, db)
    try:
        snap = json.loads(nota.snapshot_json or "{}")
    except Exception:
        snap = {}
    sell_date_label = snap.get("sell_date_label") or "—"
    if sell_date_label == "—" and item.sell_date:
        sell_date_label = (
            f"{item.sell_date.day} {BULAN.get(item.sell_date.month, '')} {item.sell_date.year}"
        )

    sig_url = ""
    if nota.signature_path:
        from . import media as media_svc

        sig_url = media_svc.media_url(nota.signature_path)

    return render(
        request,
        "nota.html",
        {
            "item": item,
            "profit": svc.item_profit(item),
            "extra": svc.item_extra_costs(item),
            "nota_no": nota.nota_no or f"LP-{item.id:05d}",
            "nota": nota,
            "signature_url": sig_url,
            "signed": bool(nota.signature_path),
            "can_void": (
                not nota.voided
                and (item.qty_remaining < item.qty_total or item.sell_price is not None)
            ),
            "shop": _nota_shop(),
            "sell_date_label": sell_date_label,
            "buyer_phone": buyer_phone,
        },
        user=user,
    )


@app.post("/item/{item_id}/nota/sign")
async def item_nota_sign(
    request: Request,
    item_id: int,
    db: Session = Depends(get_db),
):
    """Simpan TTD digital pembeli (canvas base64) ke arsip nota."""
    user = get_optional_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        return flash_redirect("/stok", err="Item tidak ditemukan.")
    if not item.sell_date and item.sell_price is None:
        return flash_redirect(f"/item/{item.id}", err="Belum ada penjualan.")

    form = await request.form()
    agreed = form.get("agreed_terms") in ("1", "on", "true", "True")
    if not agreed:
        return flash_redirect(
            f"/item/{item.id}/nota",
            err="Centang persetujuan syarat garansi dulu.",
        )
    raw_b64 = str(form.get("signature_data") or "").strip()
    if not raw_b64 or "base64," not in raw_b64:
        return flash_redirect(f"/item/{item.id}/nota", err="Tanda tangan belum diisi.")

    import base64

    try:
        header, b64data = raw_b64.split("base64,", 1)
        data = base64.b64decode(b64data)
    except Exception:
        return flash_redirect(f"/item/{item.id}/nota", err="Format tanda tangan tidak valid.")
    if len(data) < 100:
        return flash_redirect(f"/item/{item.id}/nota", err="Tanda tangan terlalu kosong.")
    if len(data) > 2 * 1024 * 1024:
        return flash_redirect(f"/item/{item.id}/nota", err="File TTD terlalu besar.")

    from . import media as media_svc

    rel = media_svc.save_upload(
        data,
        filename="ttd-pembeli.png",
        subdir=f"{item.id}/signatures",
        make_thumb=False,
    )
    # save_upload forces jpeg for photos — for PNG signature we need raw path
    # Re-save signature as PNG without heavy jpeg conversion if needed
    if not rel:
        # fallback manual write
        from pathlib import Path
        from .config import DATA_DIR
        import uuid as uuid_mod

        folder = DATA_DIR / "qc_photos" / str(item.id) / "signatures"
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{uuid_mod.uuid4().hex}.png"
        (folder / name).write_bytes(data)
        rel = (folder / name).relative_to(DATA_DIR).as_posix()
    else:
        # If converted to jpg, still ok for display
        pass

    nota = _ensure_sale_nota(db, item, user.username)
    nota.signature_path = rel
    nota.signed_at = datetime.utcnow()
    nota.agreed_terms = True
    nota.buyer_name = item.buyer or nota.buyer_name
    nota.buyer_phone = _extract_phone_from_item(item, db) or nota.buyer_phone
    db.commit()
    return flash_redirect(
        f"/item/{item.id}/nota",
        ok="Tanda tangan pembeli tersimpan. Nota diarsipkan.",
    )


@app.get("/nota", response_class=HTMLResponse)
def nota_arsip(
    request: Request,
    q: str = "",
    db: Session = Depends(get_db),
):
    """Arsip nota jual — cari pembeli / WA / no. nota (hanya website admin)."""
    user = get_optional_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    query = db.query(SaleNota).filter(SaleNota.voided == False)  # noqa: E712
    if q.strip():
        term = f"%{q.strip()}%"
        query = query.filter(
            SaleNota.buyer_name.ilike(term)
            | SaleNota.buyer_phone.ilike(term)
            | SaleNota.nota_no.ilike(term)
            | SaleNota.item_name.ilike(term)
            | SaleNota.imei.ilike(term)
        )
    rows = query.order_by(SaleNota.sell_date.desc(), SaleNota.id.desc()).limit(200).all()
    return render(
        request,
        "nota_arsip.html",
        {"rows": rows, "q": q},
        user=user,
    )


def _void_sale(db: Session, item: Item) -> str:
    """
    Batalkan penjualan: unit kembali ke stok ready.
    - Kembalikan qty
    - Hapus data jual (harga/tgl/pembeli)
    - Hapus kas masuk sale + kas keluar biaya saat jual
    - Hapus ItemCost yang dibuat saat jual
    - Hapus QC fase jual
    Data beli + QC beli tetap.
    """
    if item.qty_remaining >= item.qty_total and item.sell_price is None:
        return "Unit ini belum terjual / sudah di stok."

    # Kas: hapus pemasukan jual
    sale_entries = (
        db.query(CashEntry)
        .filter(
            CashEntry.ref_type == "item",
            CashEntry.ref_id == item.id,
            CashEntry.entry_type == "sale",
        )
        .all()
    )
    for e in sale_entries:
        db.delete(e)

    # Kas keluar biaya saat jual (bukan "Beli: ...")
    cost_cash = (
        db.query(CashEntry)
        .filter(
            CashEntry.ref_type == "item",
            CashEntry.ref_id == item.id,
            CashEntry.entry_type == "purchase",
        )
        .all()
    )
    for e in cost_cash:
        desc = (e.description or "").strip()
        if desc.startswith("Beli:"):
            continue
        db.delete(e)

    # Biaya unit yang dicatat saat jual
    for c in list(item.costs or []):
        notes = (c.notes or "").strip().lower()
        if "potong laba unit saat jual" in notes or "saat jual" in notes:
            db.delete(c)

    # QC jual (opsional) — hapus biar bersih saat jual ulang
    jual_qcs = (
        db.query(ItemQcCheck)
        .filter(ItemQcCheck.item_id == item.id, ItemQcCheck.phase == "jual")
        .all()
    )
    for qc in jual_qcs:
        db.delete(qc)

    # Arsip nota: tandai void (jangan dihapus, biar riwayat tetap ada)
    for n in (
        db.query(SaleNota)
        .filter(SaleNota.item_id == item.id, SaleNota.voided == False)  # noqa: E712
        .all()
    ):
        n.voided = True

    item.qty_remaining = item.qty_total
    item.sell_price = None
    item.sell_date = None
    item.buyer = ""
    item.buyer_phone = ""
    svc.refresh_item_status(item)
    return ""


@app.post("/item/{item_id}/batal-jual")
def item_batal_jual(
    request: Request,
    item_id: int,
    db: Session = Depends(get_db),
):
    user = get_optional_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        return flash_redirect("/stok", err="Item tidak ditemukan.")

    err = _void_sale(db, item)
    if err:
        return flash_redirect(f"/item/{item.id}", err=err)
    db.commit()
    return flash_redirect(
        f"/jual?item_id={item.id}",
        ok=f"Penjualan dibatalkan. {item.name} kembali ke stok — silakan revisi & jual ulang.",
    )


# ---------- Item detail ----------
@app.get("/item/{item_id}", response_class=HTMLResponse)
def item_detail(request: Request, item_id: int, db: Session = Depends(get_db)):
    user = get_optional_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        return flash_redirect("/stok", err="Item tidak ditemukan.")

    device_info = imei_svc.device_info_from_json(item.device_info_json)
    ext_links = imei_svc.external_check_links(item.imei, item.serial_number)
    qc_rows = (
        db.query(ItemQcCheck)
        .filter(ItemQcCheck.item_id == item.id)
        .order_by(ItemQcCheck.created_at.desc())
        .all()
    )
    qc_history = []
    for qc in qc_rows:
        try:
            ans = json.loads(qc.answers_json or "{}")
        except Exception:
            ans = {}
        try:
            photos = json.loads(qc.photos_json or "[]")
        except Exception:
            photos = []
        if not isinstance(photos, list):
            photos = []
        ok_n = sum(1 for k, v in ans.items() if v == "ok" and not str(k).endswith("_note"))
        bad_n = sum(1 for k, v in ans.items() if v == "bad" and not str(k).endswith("_note"))
        qc_history.append(
            {"qc": qc, "answers": ans, "ok": ok_n, "bad": bad_n, "photos": photos}
        )
    latest_answers = qc_history[0]["answers"] if qc_history else {}

    # group template for form
    groups: dict[str, list] = {}
    for row in QC_TEMPLATE:
        groups.setdefault(row["group"], []).append(row)

    unit_photos = _parse_photos_json(getattr(item, "unit_photos_json", None))
    threetools_photos = _parse_photos_json(getattr(item, "threetools_photos_json", None))

    return render(
        request,
        "item_detail.html",
        {
            "item": item,
            "profit": svc.item_profit(item),
            "extra": svc.item_extra_costs(item),
            "today": date.today().isoformat(),
            "device_info": device_info,
            "ext_links": ext_links,
            "qc_history": qc_history,
            "latest_answers": latest_answers,
            "qc_groups": groups,
            "qc_label": {r["key"]: r["label"] for r in QC_TEMPLATE},
            "unit_photos": unit_photos,
            "threetools_photos": threetools_photos,
        },
        user=user,
    )


@app.post("/item/{item_id}/photos")
async def item_add_photos(
    request: Request,
    item_id: int,
    db: Session = Depends(get_db),
):
    """Tambah foto unit / 3uTools dari halaman detail."""
    user = get_optional_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        return flash_redirect("/stok", err="Item tidak ditemukan.")

    form = await request.form()
    kind = str(form.get("kind") or "unit").strip()
    if kind not in ("unit", "threetools"):
        kind = "unit"

    existing = _parse_photos_json(
        item.unit_photos_json if kind == "unit" else item.threetools_photos_json
    )
    field = "unit_photo" if kind == "unit" else "threetools_photo"
    prefix = "unit" if kind == "unit" else "3utools"
    label = "Foto unit" if kind == "unit" else "3uTools"
    new_photos = await _save_upload_field(
        form,
        file_field=field,
        item_id=item.id,
        default_label=label,
        subdir_prefix=prefix,
    )
    if not new_photos:
        return flash_redirect(f"/item/{item.id}", err="Tidak ada foto yang diunggah.")
    merged = existing + new_photos
    if kind == "unit":
        item.unit_photos_json = json.dumps(merged, ensure_ascii=False)
    else:
        item.threetools_photos_json = json.dumps(merged, ensure_ascii=False)
    db.commit()
    return flash_redirect(
        f"/item/{item.id}",
        ok=f"{len(new_photos)} foto {label} ditambahkan.",
    )


def _apply_device_info_to_item(item: Item, data: dict) -> None:
    """Terapkan hasil lookup/OCR/manual ke field item."""
    if not data:
        return
    item.device_info_json = imei_svc.device_info_to_json(data)
    item.imei_provider = str(data.get("_provider") or "manual")
    item.imei_checked_at = datetime.utcnow()
    if data.get("imei"):
        item.imei = imei_svc.clean_imei(str(data["imei"])) or item.imei
    if data.get("imei2"):
        item.imei2 = imei_svc.clean_imei(str(data["imei2"])) or item.imei2
    if data.get("serial"):
        item.serial_number = imei_svc.clean_serial(str(data["serial"])) or item.serial_number
    if data.get("meid"):
        item.meid = str(data["meid"])[:32]
    model = data.get("model")
    if model and (not item.name or len(item.name) < 8):
        item.name = str(model)[:255]


@app.post("/item/{item_id}/imei")
async def item_save_imei(
    request: Request,
    item_id: int,
    db: Session = Depends(get_db),
):
    user = get_optional_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        return flash_redirect("/stok", err="Item tidak ditemukan.")

    form = await request.form()
    action = str(form.get("action") or "save")
    imei = imei_svc.clean_imei(str(form.get("imei") or ""))
    imei2 = imei_svc.clean_imei(str(form.get("imei2") or ""))
    meid = str(form.get("meid") or "").strip()
    serial = imei_svc.clean_serial(str(form.get("serial_number") or ""))
    battery = str(form.get("battery_health") or "").strip()

    if action != "manual_info":
        # manual_info membawa hidden fields; save/lookup update dari form utama
        item.imei = imei or item.imei
        item.imei2 = imei2 or item.imei2
        item.meid = meid or item.meid
        item.serial_number = serial or item.serial_number
    if battery:
        item.battery_health = battery

    msg = "IMEI / serial disimpan."
    if action == "lookup":
        ok, data, message = imei_svc.lookup_imei_api(
            imei=item.imei or imei, serial=item.serial_number or serial
        )
        if ok and data:
            _apply_device_info_to_item(item, data)
            msg = f"Lookup OK. {message}"
        else:
            msg = f"Disimpan. Lookup: {message}"
    elif action == "manual_info":
        form_dict = {k: str(form.get(k) or "") for k in form.keys()}
        info = imei_svc.build_manual_info(form_dict)
        if imei:
            info["imei"] = imei
        if imei2:
            info["imei2"] = imei2
        if serial:
            info["serial"] = serial
        if meid:
            info["meid"] = meid
        # merge existing
        old = imei_svc.device_info_from_json(item.device_info_json)
        merged = {**old, **info}
        if info:
            _apply_device_info_to_item(item, merged)
            item.imei = imei or item.imei
            item.imei2 = imei2 or item.imei2
            item.serial_number = serial or item.serial_number
            item.meid = meid or item.meid
            msg = "Info perangkat (manual) disimpan."
        else:
            msg = "IMEI/serial disimpan (tidak ada field info tambahan)."

    db.commit()
    return flash_redirect(f"/item/{item.id}", ok=msg)


def _catalog_token_ok(request: Request) -> bool:
    """Token link katalog (query ?k= atau cookie)."""
    k = (request.query_params.get("k") or request.cookies.get("catalog_k") or "").strip()
    if not k or not CATALOG_TOKEN:
        return False
    try:
        return secrets_mod.compare_digest(k, CATALOG_TOKEN)
    except Exception:
        return k == CATALOG_TOKEN


def _shop_public() -> dict:
    wa_digits = re.sub(r"\D", "", SHOP_WA)
    if wa_digits.startswith("0"):
        wa_digits = "62" + wa_digits[1:]
    ig = SHOP_IG.lstrip("@")
    tt = SHOP_TIKTOK.lstrip("@")
    return {
        "name": SHOP_NAME,
        "tagline": SHOP_TAGLINE,
        "area": SHOP_AREA,
        "wa": SHOP_WA,
        "wa_link": f"https://wa.me/{wa_digits}",
        "ig": f"@{ig}",
        "ig_link": f"https://www.instagram.com/{ig}/",
        "tiktok": f"@{tt}",
        "tiktok_link": f"https://www.tiktok.com/@{tt}",
    }


def _public_qc_summary(db: Session, item_id: int) -> dict:
    """Ringkasan + detail QC untuk konsumen."""
    qc = (
        db.query(ItemQcCheck)
        .filter(ItemQcCheck.item_id == item_id)
        .order_by(ItemQcCheck.created_at.desc())
        .first()
    )
    if not qc:
        return {
            "has_qc": False,
            "label": "Belum ada QC publik",
            "ok": 0,
            "bad": 0,
            "rows": [],
            "groups": {},
        }
    if qc.cannot_check:
        return {
            "has_qc": True,
            "label": "Dicek sebatas kondisi fisik",
            "ok": 0,
            "bad": 0,
            "rows": [],
            "groups": {},
            "cannot_check": True,
            "reason": (qc.cannot_check_reason or "").strip(),
        }
    try:
        ans = json.loads(qc.answers_json or "{}")
    except Exception:
        ans = {}
    ok_n = sum(1 for k, v in ans.items() if v == "ok" and not str(k).endswith("_note"))
    bad_n = sum(1 for k, v in ans.items() if v == "bad" and not str(k).endswith("_note"))
    if bad_n > 0:
        label = f"Ada {bad_n} poin perlu diperhatikan"
    elif ok_n > 0:
        label = f"QC Leks Phone · {ok_n} poin OK"
    else:
        label = "Unit ready"

    rows = []
    groups: dict[str, list] = {}
    for row in QC_TEMPLATE:
        key = row["key"]
        val = ans.get(key)
        if val is None or val == "":
            continue
        note = ""
        if val == "bad":
            note = str(ans.get(f"{key}_note") or "").strip()
        entry = {
            "key": key,
            "label": row["label"],
            "group": row["group"],
            "type": row["type"],
            "value": val,
            "note": note,
        }
        rows.append(entry)
        groups.setdefault(row["group"], []).append(entry)

    return {
        "has_qc": True,
        "label": label,
        "ok": ok_n,
        "bad": bad_n,
        "rows": rows,
        "groups": groups,
        "cannot_check": False,
        "notes": (qc.notes or "").strip(),
    }


PUBLIC_CATALOG_CATEGORIES = ("hp", "laptop", "tablet", "watch")


def _token_matches(token: str) -> bool:
    token = (token or "").strip()
    if not token or not CATALOG_TOKEN:
        return False
    try:
        return secrets_mod.compare_digest(token, CATALOG_TOKEN)
    except Exception:
        return token == CATALOG_TOKEN


@app.get("/katalog", response_class=HTMLResponse)
def katalog_list(request: Request, k: str = "", q: str = "", db: Session = Depends(get_db)):
    """Katalog publik — stok ready saja, tanpa data keuangan."""
    token = (k or request.cookies.get("catalog_k") or "").strip()
    if not _token_matches(token):
        return templates.TemplateResponse(
            request=request,
            name="katalog_gate.html",
            context={"shop": _shop_public(), "err": bool(k)},
        )

    # Hanya HP / laptop (Macbook) / tablet / watch — bukan aksesoris
    query = db.query(Item).filter(
        Item.qty_remaining > 0,
        Item.category.in_(PUBLIC_CATALOG_CATEGORIES),
    )
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(Item.name.ilike(like) | Item.category.ilike(like))
    items = query.order_by(Item.purchase_date.desc(), Item.id.desc()).all()

    cards = []
    for it in items:
        photos = _parse_photos_json(getattr(it, "unit_photos_json", None))
        # watermark via serve_media saat katalog; thumb tetap path biasa
        cover = photos[0]["thumb_url"] if photos else ""
        cards.append(
            {
                "id": it.id,
                "code": f"LP-{it.id:04d}",
                "name": it.name,
                "category": it.category or "hp",
                "battery": it.battery_health or "",
                "cover": cover,
                "photo_count": len(photos),
                "qc": _public_qc_summary(db, it.id),
            }
        )

    resp = templates.TemplateResponse(
        request=request,
        name="katalog.html",
        context={
            "shop": _shop_public(),
            "items": cards,
            "q": q,
            "k": token,
            "catalog_url": f"/katalog?k={token}",
        },
    )
    resp.set_cookie("catalog_k", token, max_age=60 * 60 * 24 * 30, httponly=True, samesite="lax")
    return resp


@app.get("/katalog/{item_id}", response_class=HTMLResponse)
def katalog_detail(request: Request, item_id: int, k: str = "", db: Session = Depends(get_db)):
    token = (k or request.cookies.get("catalog_k") or "").strip()
    if not _token_matches(token):
        return RedirectResponse(f"/katalog?k={k}" if k else "/katalog", status_code=303)

    item = (
        db.query(Item)
        .filter(
            Item.id == item_id,
            Item.qty_remaining > 0,
            Item.category.in_(PUBLIC_CATALOG_CATEGORIES),
        )
        .first()
    )
    if not item:
        return templates.TemplateResponse(
            request=request,
            name="katalog_detail.html",
            context={
                "shop": _shop_public(),
                "item": None,
                "k": token,
                "err": "Unit tidak tersedia / sudah terjual / bukan kategori katalog.",
            },
        )

    photos = _parse_photos_json(getattr(item, "unit_photos_json", None))
    threetools = _parse_photos_json(getattr(item, "threetools_photos_json", None))
    qc = _public_qc_summary(db, item.id)
    device = imei_svc.device_info_from_json(item.device_info_json)
    public_device = {}
    for key in ("model", "color", "storage"):
        if device.get(key):
            public_device[key] = device[key]
    imei_mask = ""
    if item.imei and len(item.imei) >= 4:
        imei_mask = "••••" + item.imei[-4:]

    wa_digits = re.sub(r"\D", "", SHOP_WA)
    if wa_digits.startswith("0"):
        wa_digits = "62" + wa_digits[1:]
    msg = (
        f"Halo Leks Phone, saya tertarik unit {item.name} "
        f"(kode LP-{item.id:04d}). Minta info harga & ketersediaan."
    )
    wa_item = f"https://wa.me/{wa_digits}?text=" + __import__("urllib.parse").parse.quote(msg)

    resp = templates.TemplateResponse(
        request=request,
        name="katalog_detail.html",
        context={
            "shop": _shop_public(),
            "k": token,
            "item": {
                "id": item.id,
                "code": f"LP-{item.id:04d}",
                "name": item.name,
                "category": item.category or "hp",
                "battery": item.battery_health or "",
                "photos": photos,
                "threetools": threetools,
                "qc": qc,
                "device": public_device,
                "imei_mask": imei_mask,
                "wa_link": wa_item,
            },
            "err": None,
        },
    )
    resp.set_cookie("catalog_k", token, max_age=60 * 60 * 24 * 30, httponly=True, samesite="lax")
    return resp


@app.get("/media/{file_path:path}")
def serve_media(file_path: str, request: Request, db: Session = Depends(get_db)):
    """Sajikan foto dari DATA_DIR (login admin ATAU token katalog)."""
    from fastapi.responses import FileResponse

    user = get_optional_user(request, db)
    catalog = _catalog_token_ok(request)
    if not user and not catalog:
        return RedirectResponse("/login", status_code=303)
    from .config import DATA_DIR
    from . import media as media_svc

    # cegah path traversal
    target = (DATA_DIR / file_path).resolve()
    root = DATA_DIR.resolve()
    if not str(target).startswith(str(root)):
        return HTMLResponse("Forbidden", status_code=403)
    if not target.is_file():
        # coba generate thumb on-demand: minta file *_t.jpg yang belum ada
        if target.stem.endswith("_t") and target.suffix.lower() in (".jpg", ".jpeg"):
            stem = target.stem
            if stem.endswith("_t"):
                main_stem = stem[:-2]
                for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                    cand = target.parent / f"{main_stem}{ext}"
                    if cand.is_file():
                        rel = cand.relative_to(root).as_posix()
                        t_rel = media_svc.ensure_thumb(rel)
                        target = (DATA_DIR / t_rel).resolve()
                        break
        if not target.is_file():
            return HTMLResponse("Not found", status_code=404)

    # Konsumen (token katalog, bukan admin): watermark LEKS PHONE
    if catalog and not user:
        try:
            rel = target.relative_to(root).as_posix()
            # jangan double-watermark
            if not Path(rel).stem.endswith("_wm"):
                wm_rel = media_svc.ensure_watermarked(rel)
                wm_target = (DATA_DIR / wm_rel).resolve()
                if wm_target.is_file():
                    target = wm_target
        except Exception:
            pass

    media_type = "image/jpeg"
    suf = target.suffix.lower()
    if suf == ".png":
        media_type = "image/png"
    elif suf == ".webp":
        media_type = "image/webp"
    elif suf == ".gif":
        media_type = "image/gif"

    return FileResponse(
        target,
        media_type=media_type,
        headers={
            "Cache-Control": "private, max-age=604800, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.post("/item/{item_id}/photos/reorder")
async def item_photos_reorder(
    request: Request,
    item_id: int,
    db: Session = Depends(get_db),
):
    """Geser urutan foto unit / 3uTools (posisi 1 = cover katalog)."""
    user = get_optional_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        return flash_redirect("/stok", err="Item tidak ditemukan.")

    form = await request.form()
    kind = str(form.get("kind") or "unit").strip()
    if kind not in ("unit", "threetools"):
        kind = "unit"
    order_raw = str(form.get("order") or "").strip()
    # order = path1||path2||path3
    paths = [p.strip() for p in order_raw.split("||") if p.strip()]
    if not paths:
        return flash_redirect(f"/item/{item.id}", err="Urutan foto kosong.")

    attr = "unit_photos_json" if kind == "unit" else "threetools_photos_json"
    existing = _parse_photos_json(getattr(item, attr, None))
    by_path = {p.get("path"): p for p in existing if p.get("path")}
    new_list = []
    for path in paths:
        if path in by_path:
            new_list.append(by_path.pop(path))
    # sisanya (jika ada) di belakang
    new_list.extend(by_path.values())
    # refresh labels "Foto unit 1"
    label_base = "Foto unit" if kind == "unit" else "3uTools"
    for i, p in enumerate(new_list, 1):
        # hanya ganti label default
        lab = (p.get("label") or "").strip()
        if not lab or lab.startswith("Foto unit") or lab.startswith("3uTools"):
            p["label"] = f"{label_base} {i}"
    setattr(item, attr, json.dumps(new_list, ensure_ascii=False))
    db.commit()
    return flash_redirect(
        f"/item/{item.id}#photos-section",
        ok=f"Urutan {label_base} disimpan (1 = foto utama).",
    )


@app.post("/ocr/screenshot")
async def ocr_screenshot_api(request: Request):
    """API: 1 atau banyak screenshot → JSON field (IMEI/serial ikut)."""
    from fastapi.responses import JSONResponse
    from . import ocr_service as ocr

    db = SessionLocal()
    try:
        user = get_optional_user(request, db)
        if not user:
            return JSONResponse({"ok": False, "message": "Silakan login dulu."}, status_code=401)
    finally:
        db.close()

    form = await request.form()
    files = await _collect_upload_bytes(form, "screenshot")
    if not files:
        return JSONResponse({"ok": False, "message": "Pilih minimal 1 file gambar."}, status_code=400)

    ok, info, ocr_text, message = ocr.process_screenshots(files)
    fields = {k: v for k, v in info.items() if not str(k).startswith("_")}
    return JSONResponse(
        {
            "ok": ok,
            "message": message,
            "fields": fields,
            "ocr_preview": (ocr_text or info.get("_ocr_preview") or "")[:2000],
            "device_info_json": imei_svc.device_info_to_json(info) if info else "",
        }
    )


@app.post("/item/{item_id}/imei-screenshot")
async def item_imei_screenshot(
    request: Request,
    item_id: int,
    db: Session = Depends(get_db),
):
    """Upload 1+ screenshot → OCR merge → isi IMEI/serial + info otomatis."""
    user = get_optional_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        return flash_redirect("/stok", err="Item tidak ditemukan.")

    form = await request.form()
    files = await _collect_upload_bytes(form, "screenshot")
    if not files:
        return flash_redirect(f"/item/{item.id}", err="Pilih minimal 1 file screenshot.")

    from . import ocr_service as ocr

    ok, info, ocr_text, message = ocr.process_screenshots(files)
    if not ok and not info:
        return flash_redirect(f"/item/{item.id}", err=message)

    old = imei_svc.device_info_from_json(item.device_info_json)
    merged = {
        **old,
        **{k: v for k, v in info.items() if not str(k).startswith("_") or k == "_ocr_preview"},
    }
    merged["_provider"] = "screenshot_ocr"
    if ocr_text:
        merged["_ocr_preview"] = ocr_text[:2500]

    if ok:
        _apply_device_info_to_item(item, merged)
        db.commit()
        return flash_redirect(
            f"/item/{item.id}",
            ok=message + " IMEI/serial ikut terisi jika terbaca. Cek & Simpan info jika perlu.",
        )

    item.device_info_json = imei_svc.device_info_to_json(merged)
    item.imei_provider = "screenshot_ocr"
    item.imei_checked_at = datetime.utcnow()
    db.commit()
    return flash_redirect(f"/item/{item.id}", err=message)


@app.post("/item/{item_id}/qc")
async def item_save_qc(
    request: Request,
    item_id: int,
    db: Session = Depends(get_db),
):
    user = get_optional_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        return flash_redirect("/stok", err="Item tidak ditemukan.")

    form = await request.form()
    phase = str(form.get("phase") or "umum").strip() or "umum"
    if phase not in ("beli", "jual", "umum"):
        phase = "umum"

    answers = _qc_answers_from_form(form)
    if answers.get("battery_health"):
        item.battery_health = str(answers["battery_health"])

    cannot = form.get("cannot_check") in ("1", "on", "true", "True")
    photos = await _save_qc_photos(form, item.id)
    qc = ItemQcCheck(
        item_id=item.id,
        phase=phase,
        contact_name=str(form.get("contact_name") or "").strip(),
        contact_phone=str(form.get("contact_phone") or "").strip(),
        qc_date=svc.parse_date(form.get("qc_date")) or date.today(),
        answers_json=json.dumps(answers, ensure_ascii=False),
        notes=str(form.get("qc_notes") or "").strip(),
        photos_json=json.dumps(photos, ensure_ascii=False),
        cannot_check=cannot,
        cannot_check_reason=str(form.get("cannot_check_reason") or "").strip(),
        created_by=user.username,
    )
    db.add(qc)
    db.commit()
    return flash_redirect(f"/item/{item.id}", ok=f"Quality check ({phase}) disimpan.")


@app.post("/item/{item_id}/cost")
def item_add_cost(
    request: Request,
    item_id: int,
    label: str = Form(...),
    amount: str = Form(...),
    cost_date: str = Form(""),
    affect_cash: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    user = get_optional_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        return flash_redirect("/stok", err="Item tidak ditemukan.")
    amt = svc.parse_money(amount)
    cdate = svc.parse_date(cost_date) or date.today()
    cost = ItemCost(item_id=item.id, label=label.strip(), amount=amt, cost_date=cdate)
    db.add(cost)
    if affect_cash:
        svc.add_cash(
            db,
            txn_date=cdate,
            direction="out",
            entry_type="purchase",
            amount=amt,
            description=f"Biaya {label} — {item.name}",
            ref_type="item",
            ref_id=item.id,
            created_by=user.username,
        )
    db.commit()
    return flash_redirect(f"/item/{item.id}", ok="Biaya ditambahkan.")


@app.post("/item/{item_id}/notes")
def item_notes(
    request: Request,
    item_id: int,
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    user = get_optional_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        return flash_redirect("/stok", err="Item tidak ditemukan.")
    item.notes = notes
    db.commit()
    return flash_redirect(f"/item/{item.id}", ok="Catatan disimpan.")


@app.post("/item/{item_id}/set-sell")
async def item_set_sell(
    request: Request,
    item_id: int,
    db: Session = Depends(get_db),
):
    user = get_optional_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item or item.qty_remaining <= 0:
        return flash_redirect("/stok", err="Item tidak tersedia.")

    form = await request.form()
    try:
        qty = max(1, min(int(str(form.get("qty") or "1")), item.qty_remaining))
    except ValueError:
        qty = 1
    price = svc.parse_money(form.get("sell_price"))
    sdate = svc.parse_date(form.get("sell_date")) or date.today()
    buyer = str(form.get("buyer") or "").strip()
    buyer_phone = str(form.get("buyer_phone") or "").strip()
    notes = str(form.get("notes") or "").strip()
    affect_cash = form.get("affect_cash") in ("1", "on", "true", "True")
    costs_affect_cash = form.get("costs_affect_cash") in ("1", "on", "true", "True")
    charger = svc.parse_money(form.get("charger_price"))
    extra_costs = _parse_cost_rows(form)

    item.qty_remaining -= qty
    if item.sell_price is None:
        item.sell_price = price
    else:
        item.sell_price = (item.sell_price or 0) + price
    item.sell_date = sdate
    if buyer:
        item.buyer = buyer
    if buyer_phone:
        item.buyer_phone = buyer_phone
    if notes:
        item.notes = notes if not item.notes else (item.notes + " | " + notes)
    svc.refresh_item_status(item)
    db.flush()

    cost_entries: list[tuple[str, float]] = []
    if charger > 0:
        cost_entries.append(("Charger", charger))
    cost_entries.extend(extra_costs)
    total_extra = 0.0
    for label, amt in cost_entries:
        db.add(
            ItemCost(
                item_id=item.id,
                label=label,
                amount=amt,
                cost_date=sdate,
                notes="potong laba unit saat jual",
            )
        )
        total_extra += amt
        if costs_affect_cash:
            svc.add_cash(
                db,
                txn_date=sdate,
                direction="out",
                entry_type="purchase",
                amount=amt,
                description=f"{label}: {item.name}",
                ref_type="item",
                ref_id=item.id,
                created_by=user.username,
            )

    if affect_cash:
        svc.add_cash(
            db,
            txn_date=sdate,
            direction="in",
            entry_type="sale",
            amount=price,
            description=f"Jual: {item.name}" + (f" · {buyer}" if buyer else ""),
            ref_type="item",
            ref_id=item.id,
            created_by=user.username,
        )
    db.commit()
    db.refresh(item)
    profit = svc.item_profit(item)
    msg = "Penjualan diupdate."
    if total_extra > 0:
        msg += f" Biaya {idr(total_extra)} dipotong dari laba unit."
    if profit is not None:
        msg += f" Laba unit: {idr(profit)}."
    return flash_redirect(f"/item/{item.id}", ok=msg)


# ---------- Kas ----------
@app.get("/kas", response_class=HTMLResponse)
def kas_page(request: Request, db: Session = Depends(get_db)):
    user = get_optional_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    entries = (
        db.query(CashEntry).order_by(CashEntry.txn_date.desc(), CashEntry.id.desc()).limit(100).all()
    )
    return render(
        request,
        "kas.html",
        {
            "saldo": svc.cash_balance(db),
            "kas_rekening": svc.kas_di_rekening(db),
            "modal_setor": svc.modal_disetor(db),
            "modal_barang": svc.modal_in_goods(db),
            "entries": entries,
            "today": date.today().isoformat(),
        },
        user=user,
    )


@app.post("/kas")
def kas_post(
    request: Request,
    entry_type: str = Form(...),
    txn_date: str = Form(...),
    amount: str = Form(...),
    description: str = Form(""),
    db: Session = Depends(get_db),
):
    user = get_optional_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    amt = svc.parse_money(amount)
    tdate = svc.parse_date(txn_date) or date.today()
    mapping = {
        "capital": ("in", "capital"),
        "withdraw": ("out", "withdraw"),
        "adjust_in": ("in", "adjust"),
        "adjust_out": ("out", "adjust"),
    }
    if entry_type not in mapping:
        return flash_redirect("/kas", err="Jenis tidak valid.")
    direction, etype = mapping[entry_type]
    labels = {
        "capital": "Setor modal",
        "withdraw": "Tarik pribadi",
        "adjust": "Penyesuaian",
    }
    svc.add_cash(
        db,
        txn_date=tdate,
        direction=direction,
        entry_type=etype,
        amount=amt,
        description=description.strip() or labels.get(etype, etype),
        created_by=user.username,
    )
    db.commit()
    return flash_redirect("/kas", ok="Entri kas disimpan.")


# ---------- Operasional ----------
@app.get("/operasional", response_class=HTMLResponse)
def ops_page(request: Request, db: Session = Depends(get_db)):
    user = get_optional_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    expenses = (
        db.query(OperationalExpense)
        .order_by(OperationalExpense.expense_date.desc(), OperationalExpense.id.desc())
        .limit(100)
        .all()
    )
    return render(
        request,
        "operasional.html",
        {"expenses": expenses, "today": date.today().isoformat()},
        user=user,
    )


@app.post("/operasional")
def ops_post(
    request: Request,
    expense_date: str = Form(...),
    category: str = Form("umum"),
    amount: str = Form(...),
    description: str = Form(""),
    db: Session = Depends(get_db),
):
    user = get_optional_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    amt = svc.parse_money(amount)
    edate = svc.parse_date(expense_date) or date.today()
    cash = svc.add_cash(
        db,
        txn_date=edate,
        direction="out",
        entry_type="operational",
        amount=amt,
        description=description.strip() or f"Ops: {category}",
        ref_type="operational",
        created_by=user.username,
    )
    db.flush()
    exp = OperationalExpense(
        expense_date=edate,
        category=(category or "umum").strip(),
        amount=amt,
        description=description.strip(),
        cash_entry_id=cash.id,
        created_by=user.username,
    )
    db.add(exp)
    db.commit()
    return flash_redirect("/operasional", ok="Pengeluaran operasional disimpan.")


# ---------- Laporan ----------
@app.get("/laporan", response_class=HTMLResponse)
def laporan(
    request: Request,
    month: Optional[int] = None,
    year: Optional[int] = None,
    db: Session = Depends(get_db),
):
    user = get_optional_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    today = date.today()
    month = int(month or today.month)
    year = int(year or today.year)
    start, end = svc.month_bounds(year, month)
    omzet = svc.revenue_in_month(db, year, month)
    laba = svc.profit_in_month(db, year, month)
    ops = svc.operational_in_range(db, start, end)
    sold = svc.sold_items_for_month(db, year, month)
    sold_items = [(it, svc.item_profit(it)) for it in sold]
    partners = active_partners(db)
    bagi_hasil = svc.split_profit(laba, partners)
    bagi_hasil_bersih = svc.split_profit(laba - ops, partners)
    years = list(range(today.year - 2, today.year + 2))
    return render(
        request,
        "laporan.html",
        {
            "month": month,
            "year": year,
            "bulan_nama": BULAN,
            "years": years,
            "omzet": omzet,
            "laba": laba,
            "ops": ops,
            "laba_bersih": laba - ops,
            "sold_items": sold_items,
            "bagi_hasil": bagi_hasil,
            "bagi_hasil_bersih": bagi_hasil_bersih,
            "partners": partners,
        },
        user=user,
    )


def _xlsx_response(data: bytes, filename: str) -> Response:
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


def _guess_sales_method(notes: str) -> str:
    """Metode penjualan: utamakan isi field notes (form Metode penjualan)."""
    raw = (notes or "").strip()
    if not raw:
        return "COD"
    # Jika user isi singkat (COD, Shopee, …) pakai apa adanya (kapital rapi)
    first = re.split(r"[|·,\n]", raw)[0].strip()
    low = first.lower()
    known = {
        "shopee": "Shopee",
        "tokopedia": "Tokopedia",
        "toped": "Tokopedia",
        "tiktok": "TikTok",
        "tik tok": "TikTok",
        "transfer": "Transfer",
        "cod": "COD",
        "online": "Online",
        "cherish": "Cherish",
        "toco": "Toco",
    }
    if low in known:
        return known[low]
    for key, label in known.items():
        if key in low:
            return label
    # Teks bebas → tampilkan di kolom metode (maks 40 char)
    return first[:40] if first else "COD"


def _extract_buyer_from_notes(notes: str) -> str:
    """Ambil nama pembeli dari catatan impor/lama jika field buyer kosong."""
    n = notes or ""
    for pat in (
        r"(?:pembeli|buyer)\s*[:=]\s*([^|·\n]+)",
        r"(?:atas nama|a/?n)\s*[:=]?\s*([^|·\n]+)",
    ):
        m = re.search(pat, n, re.I)
        if m:
            name = m.group(1).strip(" .-")
            if name and name not in ("-", "—"):
                return name
    return ""


def _extract_phone_from_item(item: Item, db: Session) -> str:
    """No. WA/HP pembeli: field item, QC jual, atau tag di notes."""
    phone = (getattr(item, "buyer_phone", None) or "").strip()
    if phone:
        return phone
    jual_qc = (
        db.query(ItemQcCheck)
        .filter(ItemQcCheck.item_id == item.id, ItemQcCheck.phase == "jual")
        .order_by(ItemQcCheck.created_at.desc())
        .first()
    )
    if jual_qc and (jual_qc.contact_phone or "").strip():
        return jual_qc.contact_phone.strip()
    if item.notes:
        m = re.search(
            r"(?:^|\|\s*)(?:HP|WA|Whats?App|no\.?\s*hp|telepon)\s*[:=]\s*([0-9+\-\s]{8,20})",
            item.notes,
            re.I,
        )
        if m:
            return re.sub(r"\s+", "", m.group(1).strip())
    return ""


def _charger_and_extra(item: Item) -> tuple[float, float, str]:
    """
    Pisah biaya 'Charger' vs biaya lain-lain.
    Return (charger, extra_total, catatan_biaya) — catatan untuk kolom Excel
    berisi rincian biaya lain-lain transaksi (bukan charger).
    """
    charger = 0.0
    extra = 0.0
    parts: list[str] = []
    for c in item.costs or []:
        lab_raw = (c.label or "").strip() or "Biaya"
        lab = lab_raw.lower()
        amt = float(c.amount or 0)
        if amt == 0:
            continue
        if "charger" in lab:
            charger += amt
        else:
            extra += amt
            # Format: "Makan 15.000" atau "Packing"
            try:
                amt_s = f"{int(round(amt)):,}".replace(",", ".")
            except Exception:
                amt_s = str(amt)
            parts.append(f"{lab_raw} {amt_s}")
    catatan = " · ".join(parts) if parts else ""
    return charger, extra, catatan


@app.get("/export/cashflow.xlsx")
def export_cashflow_xlsx(request: Request, db: Session = Depends(get_db)):
    """
    Satu file Excel lengkap ala spreadsheet acuan:
    Rekap Stok + Penjualan Semua + Laporan Bulanan + sheet tiap bulan
    + Kas + Operasional + Ringkasan.
    """
    user = get_optional_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    items = db.query(Item).order_by(Item.purchase_date.asc(), Item.id.asc()).all()
    stock_rows = []
    sales_rows = []
    total_omzet = 0.0
    total_laba = 0.0
    sold_count = 0
    ready_count = 0

    for it in items:
        sold = it.qty_remaining <= 0 or it.status == "sold"
        if it.qty_remaining > 0:
            ready_count += 1
        stock_rows.append(
            {
                "purchase_date": it.purchase_date,
                "name": it.name,
                "supplier": it.supplier or "",
                "buy": it.buy_price,
                "sold": sold,
                "status": it.status,
                "category": it.category,
                "imei": it.imei or "",
                "serial": it.serial_number or "",
                "notes": it.notes or "",
            }
        )
        # baris penjualan: ada harga jual / sudah berkurang qty
        if it.sell_price is not None and (sold or it.qty_remaining < it.qty_total):
            charger, extra, cost_notes = _charger_and_extra(it)
            profit = svc.item_profit(it)
            if profit is None:
                profit = (it.sell_price or 0) - (it.buy_price or 0) - charger - extra
            total_omzet += float(it.sell_price or 0)
            total_laba += float(profit or 0)
            sold_count += 1
            sdate = it.sell_date
            month_label = ""
            year_n = None
            month_n = None
            if sdate:
                month_label = f"{BULAN.get(sdate.month, sdate.month)} {sdate.year}"
                year_n = sdate.year
                month_n = sdate.month
            elif it.source_month:
                month_label = it.source_month
                # coba parse "Februari" / "Februari 2026"
                sm = (it.source_month or "").strip()
                for mi, mn in BULAN.items():
                    if mn.lower() in sm.lower():
                        month_n = mi
                        break
                ym = re.search(r"(20\d{2})", sm)
                if ym:
                    year_n = int(ym.group(1))
                elif month_n:
                    year_n = date.today().year
            buyer_name = (it.buyer or "").strip()
            if not buyer_name or buyer_name in ("-", "—"):
                buyer_name = _extract_buyer_from_notes(it.notes or "")
            if not buyer_name:
                buyer_name = "-"
            buyer_wa = _extract_phone_from_item(it, db)
            # Catatan Excel = rincian biaya lain-lain transaksi
            sales_rows.append(
                {
                    "sell_date": sdate,
                    "month": month_label,
                    "year": year_n,
                    "month_num": month_n,
                    "method": _guess_sales_method(it.notes or ""),
                    "buyer": buyer_name,
                    "buyer_phone": buyer_wa,
                    "name": it.name,
                    "buy": it.buy_price,
                    "charger": charger,
                    "sell": it.sell_price or 0,
                    "extra": extra,
                    "profit": profit,
                    "imei": it.imei or "",
                    "serial": it.serial_number or "",
                    "notes": cost_notes,
                }
            )

    # urut penjualan by date
    sales_rows.sort(
        key=lambda r: (r.get("sell_date") or date.min, r.get("name") or "")
    )

    cash_entries = (
        db.query(CashEntry).order_by(CashEntry.txn_date.asc(), CashEntry.id.asc()).all()
    )
    cash_rows = [
        {
            "txn_date": e.txn_date,
            "direction": e.direction,
            "entry_type": e.entry_type,
            "amount": e.amount,
            "description": e.description or "",
            "created_by": e.created_by or "",
        }
        for e in cash_entries
    ]

    ops = (
        db.query(OperationalExpense)
        .order_by(OperationalExpense.expense_date.asc(), OperationalExpense.id.asc())
        .all()
    )
    ops_rows = [
        {
            "expense_date": o.expense_date,
            "category": o.category or "",
            "amount": o.amount,
            "description": o.description or "",
        }
        for o in ops
    ]
    total_ops = sum(float(o.amount or 0) for o in ops)

    partners = active_partners(db)
    summary = {
        "modal_setor": svc.modal_disetor(db),
        "modal_barang": svc.modal_in_goods(db),
        "kas_rekening": svc.kas_di_rekening(db),
        "saldo_buku": svc.cash_balance(db),
        "ready_count": ready_count,
        "sold_count": sold_count,
        "total_omzet": total_omzet,
        "total_laba": total_laba,
        "total_ops": total_ops,
        "laba_bersih": total_laba - total_ops,
    }

    data = xlsx.export_cashflow_workbook(
        stock_rows=stock_rows,
        sales_rows=sales_rows,
        cash_rows=cash_rows,
        ops_rows=ops_rows,
        summary=summary,
        partners_split=svc.split_profit(total_laba, partners),
    )
    return _xlsx_response(
        data, f"leks-phone-cashflow-{date.today().isoformat()}.xlsx"
    )


# ---------- Import ----------
HEADER_MARKERS = ("waktu pembelian", "barang", "harga beli")


def _is_header_row(row: list[str]) -> bool:
    joined = " ".join(c.strip().lower() for c in row if c)
    return all(m in joined for m in ("waktu", "barang")) or (
        "harga beli" in joined and "barang" in joined
    )


def _is_truthy_sold(val: str) -> bool:
    v = (val or "").strip().upper()
    return v in ("TRUE", "1", "YES", "YA", "Y", "SOLD", "✓", "V")


def _parse_month_from_header(row: list[str]) -> str:
    for c in row:
        t = (c or "").strip()
        if re.search(
            r"januari|februari|maret|april|mei|juni|juli|agustus|september|oktober|november|desember|jan|feb|mar|apr|may|jun|jul|aug|sep|okt|nov|des",
            t,
            re.I,
        ):
            return t
    return ""


def import_csv_content(
    db: Session,
    content: str,
    *,
    capital: float = 0,
    snapshot_cash: bool = True,
    username: str = "admin",
) -> str:
    # strip BOM
    if content.startswith("\ufeff"):
        content = content[1:]
    reader = csv.reader(io.StringIO(content))
    rows = list(reader)
    if not rows:
        return "File kosong."

    current_month = ""
    created = 0
    skipped = 0

    for row in rows:
        if not row or all(not (c or "").strip() for c in row):
            continue
        # pad
        while len(row) < 7:
            row.append("")

        if _is_header_row(row):
            current_month = _parse_month_from_header(row) or current_month
            continue

        # skip summary lines
        joined = " ".join(row).lower()
        if "modal" in joined and not row[2].strip().lower().startswith("iphone"):
            # lines like Modal, Sisa modal
            if any(x in joined for x in ("sisa modal", "modal dalam", "modal,")):
                skipped += 1
                continue
            if row[3] and "modal" in (row[3] or "").lower():
                skipped += 1
                continue

        no, waktu, barang, tempat, harga, terjual, catatan = row[:7]
        barang = (barang or "").strip()
        if not barang:
            skipped += 1
            continue
        # skip if no looks non-numeric and no price
        price = svc.parse_money(harga)
        if price <= 0 and not waktu:
            skipped += 1
            continue

        pdate = svc.parse_date(waktu)
        sold_flag = _is_truthy_sold(terjual)
        notes = (catatan or "").strip()
        kind, qty = svc.guess_kind_and_qty(barang, notes)
        # remaining from notes like "6pcs" for bulk partial
        qty_remaining = 0 if sold_flag else qty
        if kind == "bulk" and not sold_flag:
            m = re.search(r"(\d+)\s*pcs", notes, re.I)
            # notes sometimes remaining sold count ambiguous — keep full qty if not sold
            pass
        if sold_flag and kind == "bulk":
            qty_remaining = 0

        # FALSE means still stock
        if not sold_flag:
            qty_remaining = qty

        item = Item(
            name=barang,
            category=svc.guess_category(barang),
            kind=kind,
            purchase_date=pdate,
            supplier=(tempat or "").strip(),
            buy_price=price,
            qty_total=qty,
            qty_remaining=qty_remaining,
            status="sold" if qty_remaining <= 0 else ("partial" if qty_remaining < qty else "ready"),
            sell_price=None,
            sell_date=None,
            notes=notes,
            source_month=current_month,
            imported=True,
        )
        db.add(item)
        created += 1

    db.flush()

    msg_parts = [f"Import {created} item (skip {skipped})."]
    modal_barang = svc.modal_in_goods(db)

    if capital > 0:
        existing_capital = (
            db.query(CashEntry).filter(CashEntry.entry_type == "capital").first()
        )
        if not existing_capital:
            svc.add_cash(
                db,
                txn_date=date.today(),
                direction="in",
                entry_type="capital",
                amount=capital,
                description="Modal awal (import)",
                created_by=username,
            )
            db.flush()
            msg_parts.append(f"Setor modal {idr(capital)}.")
        else:
            msg_parts.append("Modal sudah ada, tidak ditambah lagi.")

    if snapshot_cash and capital > 0:
        # Pola spreadsheet: sisa kas ≈ modal disetor − nilai stok ready
        target = capital - modal_barang
        bal = svc.cash_balance(db)
        delta = target - bal
        if abs(delta) > 1:
            svc.add_cash(
                db,
                txn_date=date.today(),
                direction="in" if delta > 0 else "out",
                entry_type="adjust",
                amount=abs(delta),
                description="Penyesuaian kas snapshot import (modal − stok ready)",
                created_by=username,
            )
            db.flush()
            msg_parts.append(
                f"Kas disesuaikan ke {idr(target)} (modal − stok ready {idr(modal_barang)})."
            )
        msg_parts.append(f"Saldo kas sekarang {idr(svc.cash_balance(db))}.")

    db.commit()
    return " ".join(msg_parts)


@app.get("/import", response_class=HTMLResponse)
def import_page(request: Request, db: Session = Depends(get_db)):
    user = get_optional_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return render(request, "import.html", {"last_result": None}, user=user)


@app.post("/tools/optimize-photos")
def tools_optimize_photos(request: Request, db: Session = Depends(get_db)):
    """Kompres semua foto lama di volume (tanpa upload ulang)."""
    user = get_optional_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    from . import media as media_svc

    stats = media_svc.reprocess_all_photos()
    path_map: dict = stats.get("path_map") or {}

    # Update path di DB (item + QC)
    updated_items = 0
    for item in db.query(Item).all():
        changed = False
        for attr in ("unit_photos_json", "threetools_photos_json"):
            raw = getattr(item, attr, None) or ""
            new_raw = media_svc.rewrite_photo_json(raw, path_map)
            if new_raw is not None:
                setattr(item, attr, new_raw)
                changed = True
            elif raw:
                # refresh thumb_url meski path sama
                new_raw2 = media_svc.rewrite_photo_json(raw, {})
                if new_raw2 is not None:
                    setattr(item, attr, new_raw2)
                    changed = True
        if changed:
            updated_items += 1

    updated_qc = 0
    for qc in db.query(ItemQcCheck).all():
        raw = qc.photos_json or ""
        new_raw = media_svc.rewrite_photo_json(raw, path_map)
        if new_raw is None and raw:
            new_raw = media_svc.rewrite_photo_json(raw, {})
        if new_raw is not None:
            qc.photos_json = new_raw
            updated_qc += 1

    db.commit()

    mb = stats.get("bytes_saved", 0) / (1024 * 1024)
    msg = (
        f"Kompres foto selesai. Diproses {stats.get('processed', 0)} file "
        f"(scan {stats.get('scanned', 0)}, skip {stats.get('skipped', 0)}, "
        f"error {stats.get('errors', 0)}). "
        f"Hemat ~{mb:.1f} MB. "
        f"Update DB: {updated_items} item, {updated_qc} QC."
    )
    return flash_redirect("/import", ok=msg)


@app.post("/import/google")
def import_google_post(
    request: Request,
    capital: str = Form("50000000"),
    sheet_url: str = Form(""),
    db: Session = Depends(get_db),
):
    user = get_optional_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    from .importer import import_full_from_google

    try:
        result = import_full_from_google(
            db,
            capital=svc.parse_money(capital) or 50_000_000,
            username=user.username,
            reset=True,
            sheet_url=sheet_url or "",
        )
    except Exception as e:
        return flash_redirect("/import", err=f"Gagal import Google Sheets: {e}")
    return flash_redirect("/", ok=result)


@app.post("/import")
async def import_post(
    request: Request,
    file: UploadFile = File(...),
    capital: str = Form("0"),
    snapshot_cash: Optional[str] = Form(None),
    import_kind: str = Form("stock"),
    month_label: str = Form("Import"),
    db: Session = Depends(get_db),
):
    user = get_optional_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    try:
        if import_kind == "sales":
            from .importer import import_sales_csv_file

            result = import_sales_csv_file(
                db, text, month_label or "Import", user.username
            )
        else:
            result = import_csv_content(
                db,
                text,
                capital=svc.parse_money(capital),
                snapshot_cash=bool(snapshot_cash),
                username=user.username,
            )
    except Exception as e:
        return flash_redirect("/import", err=f"Gagal import: {e}")

    return flash_redirect("/", ok=result)


# ---------- Partner / bagi hasil ----------
@app.get("/partner", response_class=HTMLResponse)
def partner_page(request: Request, db: Session = Depends(get_db)):
    user = get_optional_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return render(
        request,
        "partner.html",
        {"partners": db.query(Partner).order_by(Partner.sort_order, Partner.id).all()},
        user=user,
    )


@app.post("/partner/save")
async def partner_save(request: Request, db: Session = Depends(get_db)):
    user = get_optional_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    partners = db.query(Partner).all()
    total = 0.0
    for p in partners:
        key = f"pct_{p.id}"
        if key in form:
            try:
                p.share_percent = float(str(form[key]).replace(",", "."))
            except ValueError:
                pass
            total += p.share_percent
        act_key = f"active_{p.id}"
        p.active = act_key in form
    if abs(total - 100) > 0.5 and total > 0:
        # masih simpan, tapi beri peringatan
        db.commit()
        return flash_redirect(
            "/partner",
            ok=f"Disimpan. Total porsi {total:.0f}% (ideal 100%).",
        )
    db.commit()
    return flash_redirect("/partner", ok="Porsi bagi hasil disimpan.")


@app.post("/partner/add")
def partner_add(
    request: Request,
    name: str = Form(...),
    share_percent: str = Form("0"),
    db: Session = Depends(get_db),
):
    user = get_optional_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    n = name.strip()
    if not n:
        return flash_redirect("/partner", err="Nama wajib diisi.")
    if db.query(Partner).filter(Partner.name == n).first():
        return flash_redirect("/partner", err="Partner sudah ada.")
    pct = svc.parse_money(share_percent) or 0
    # parse_money strips non-digits badly for small numbers - use float
    try:
        pct = float(str(share_percent).replace(",", "."))
    except ValueError:
        pct = 0
    db.add(Partner(name=n, share_percent=pct, active=True, sort_order=99))
    db.commit()
    return flash_redirect("/partner", ok=f"Partner {n} ditambahkan.")


# ---------- health ----------
@app.get("/health")
def health(db: Session = Depends(get_db)):
    try:
        names = [u.username for u in db.query(User).all()]
        return {
            "ok": True,
            "app": "hp-rekap",
            "users": names,
            "admin_env": ADMIN_USERNAME,
            "db": str(DB_PATH),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

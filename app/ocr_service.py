"""
OCR screenshot hasil cek IMEI (iUnlocker / IMEICheck) → field terstruktur.
Butuh: Pillow + pytesseract + binary tesseract-ocr di server.
"""
from __future__ import annotations

import io
import re
from typing import Any

from . import imei_service as imei_svc


def _tesseract_available() -> tuple[bool, str]:
    try:
        import pytesseract  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError as e:
        return False, f"Package OCR belum terpasang: {e}"
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        return True, "ok"
    except Exception as e:
        return False, (
            "Tesseract OCR belum terpasang di server. "
            f"Detail: {e}"
        )


def image_bytes_to_text(data: bytes) -> tuple[bool, str, str]:
    """Returns (ok, text, message)."""
    ok, msg = _tesseract_available()
    if not ok:
        return False, "", msg
    try:
        import pytesseract
        from PIL import Image, ImageEnhance, ImageOps

        img = Image.open(io.BytesIO(data))
        # normalisasi
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        # perbesar sedikit untuk screenshot HP
        w, h = img.size
        if w < 900:
            scale = 900 / max(w, 1)
            img = img.resize((int(w * scale), int(h * scale)))
        gray = ImageOps.grayscale(img)
        gray = ImageOps.autocontrast(gray)
        gray = ImageEnhance.Contrast(gray).enhance(1.4)
        # OCR English (label situs cek IMEI biasanya EN)
        text = pytesseract.image_to_string(gray, lang="eng")
        text = text.replace("\x0c", "\n")
        if not text.strip():
            return False, "", "Tidak ada teks terbaca. Coba foto lebih jelas / crop hasil cek saja."
        return True, text, "OCR berhasil."
    except Exception as e:
        return False, "", f"Gagal OCR: {e}"


def _norm_label(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9+/\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# label OCR (normalisasi) → key internal
_LABEL_MAP: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^(imei\s*2|imei2)$"), "imei2"),
    (re.compile(r"^(imei\s*1|imei)$"), "imei"),
    (re.compile(r"^meid$"), "meid"),
    (re.compile(r"^serial(\s*number)?$"), "serial"),
    (re.compile(r"^(model|modeldesc|model\s*desc)$"), "model"),
    (re.compile(r"^(model\s*number|modelnumber)$"), "model_number"),
    (re.compile(r"^(colour|color|warna)$"), "color"),
    (re.compile(r"^(storage|capacity|memory|penyimpanan)$"), "storage"),
    (re.compile(r"^(sim\s*lock(\s*status)?|simlock)$"), "sim_lock"),
    (re.compile(r"^(find\s*my(\s*iphone)?|fmi|icloud(\s*status)?)$"), "fmi"),
    (re.compile(r"^(warranty(\s*status|\s*name)?|garansi)$"), "warranty"),
    (re.compile(r"^(apple\s*care(\s*eligible)?)$"), "apple_care"),
    (re.compile(r"^(estimated\s*purchase\s*date|purchase\s*date|tgl\s*beli)$"), "purchase_date"),
    (re.compile(r"^(estimated\s*expiration\s*date|warranty\s*expired|akhir\s*garansi)$"), "warranty_end"),
    (re.compile(r"^(country\s*of\s*purchase|negara)$"), "country"),
    (re.compile(r"^(model\s*region|region)$"), "region"),
    (re.compile(r"^(sim\s*config|sim\s*configuration)$"), "sim_config"),
    (re.compile(r"^(demo(\s*unit)?)$"), "demo"),
    (re.compile(r"^refurbished$"), "refurbished"),
    (re.compile(r"^(replacement(\s*device)?|replaced\s*device)$"), "replacement"),
    (re.compile(r"^(activation\s*status|activated|past\s*first\s*activation)$"), "activated"),
    (re.compile(r"^(registered\s*device)$"), "registered"),
    (re.compile(r"^(valid\s*purchase\s*date)$"), "valid_purchase"),
    (re.compile(r"^(loaner(\s*device)?)$"), "loaner"),
]


def _match_label(label: str) -> str | None:
    n = _norm_label(label)
    if not n:
        return None
    for pat, key in _LABEL_MAP:
        if pat.match(n):
            return key
    # partial contains
    if "serial" in n:
        return "serial"
    if "imei 2" in n or n.endswith("imei2"):
        return "imei2"
    if "imei" in n and "2" not in n:
        return "imei"
    if "simlock" in n or "sim lock" in n:
        return "sim_lock"
    if "find my" in n or n == "fmi" or "icloud" in n:
        return "fmi"
    if "warranty" in n and "expir" not in n:
        return "warranty"
    if "purchase" in n and "valid" not in n:
        return "purchase_date"
    if "expir" in n:
        return "warranty_end"
    if "country" in n:
        return "country"
    if "refurbished" in n:
        return "refurbished"
    if "replacement" in n or "replaced" in n:
        return "replacement"
    if "apple care" in n:
        return "apple_care"
    if "activated" in n or "activation" in n:
        return "activated"
    return None


def _clean_value(key: str, val: str) -> str:
    val = val.strip()
    val = re.sub(r"\s+", " ", val)
    # buang noise OCR umum
    val = val.replace("|", "I")
    if key in ("imei", "imei2", "meid"):
        digits = re.sub(r"\D", "", val)
        # IMEI sering 15 digit; toleransi 14-16
        if len(digits) >= 14:
            return digits[:16]
        return digits
    if key == "serial":
        return _normalize_serial_candidate(val)
    # status yes/no
    if key in ("demo", "refurbished", "replacement", "apple_care", "registered", "valid_purchase", "loaner"):
        low = val.lower()
        if re.search(r"\byes\b|\bya\b", low):
            return "Yes"
        if re.search(r"\bno\b|\btidak\b", low):
            return "No"
    if key == "sim_lock":
        if re.search(r"unlock", val, re.I):
            return "Unlocked"
        if re.search(r"lock", val, re.I):
            return "Locked"
    if key == "fmi":
        if re.search(r"\boff\b|\bno\b|kosong", val, re.I):
            return "OFF"
        if re.search(r"\bon\b|\byes\b|lost|erased", val, re.I):
            return val.strip()[:80]
    return val[:200]


# Kata yang sering salah dianggap serial (OCR / label status)
_SERIAL_BLOCKLIST = {
    "ACTIVATION",
    "ACTIVATED",
    "WARRANTY",
    "REFURBISHED",
    "REPLACEMENT",
    "REGISTERED",
    "PURCHASE",
    "EXPIRATION",
    "TECHNICAL",
    "COVERAGE",
    "SUPPORT",
    "BLACKLIST",
    "UNLOCKED",
    "LOCKED",
    "JAPAN",
    "GLOBAL",
    "IPHONE",
    "ANDROID",
    "SUCCESS",
    "SERIALNUMBER",
    "SERIAL",
    "NUMBER",
    "STATUS",
    "DEVICE",
    "FIND",
    "ICLOUD",
    "APPLE",
    "CARE",
    "DEMO",
    "UNIT",
    "VALID",
    "LOANER",
    "ESTIMATED",
    "COUNTRY",
    "OF",
    "THE",
    "AND",
    "FOR",
    "CHECK",
    "RESULT",
    "PROVIDED",
    "IUNLOCKER",
    "IMEICHECK",
}


def _normalize_serial_candidate(val: str) -> str:
    """Serial number = kombinasi huruf kapital + angka (bukan kata status)."""
    s = re.sub(r"[^A-Za-z0-9]", "", (val or "")).upper()
    if not s or len(s) < 8 or len(s) > 14:
        return ""
    if s.isdigit() or s.isalpha():
        # serial murni angka = IMEI; murni huruf sering label (ACTIVATION)
        return ""
    if s in _SERIAL_BLOCKLIST:
        return ""
    # tolak jika mengandung kata blocklist sebagai whole
    for bad in _SERIAL_BLOCKLIST:
        if len(bad) >= 5 and bad in s and s == bad:
            return ""
    # harus ada minimal 1 huruf dan 1 angka
    if not re.search(r"[A-Z]", s) or not re.search(r"[0-9]", s):
        return ""
    return s


def parse_imei_check_text(text: str) -> dict[str, Any]:
    """Parse teks OCR menjadi dict field standar."""
    raw_lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    found: dict[str, str] = {}

    # 1) pola Label: Value / Label Value di baris sama
    for ln in raw_lines:
        # Title-like: IPHONE 11 BLACK 128GB
        if re.match(r"^IPHONE\s+\d", ln, re.I) and "model" not in found:
            found["model"] = ln.strip()
            m = re.search(r"(\d+\s*GB)", ln, re.I)
            if m:
                found["storage"] = m.group(1).replace(" ", "").upper()
            continue

        m = re.match(r"^(.{2,40}?)[:：]\s*(.+)$", ln)
        if m:
            key = _match_label(m.group(1))
            if key and key not in found:
                cleaned = _clean_value(key, m.group(2))
                if cleaned:
                    found[key] = cleaned
            continue

        m2 = re.match(r"^([A-Za-z][A-Za-z0-9 /+]{1,35}?)\s{2,}(.+)$", ln)
        if m2:
            key = _match_label(m2.group(1))
            if key and key not in found:
                cleaned = _clean_value(key, m2.group(2))
                if cleaned:
                    found[key] = cleaned

    # 2) baris berpasangan: label lalu value di baris berikutnya
    for i, ln in enumerate(raw_lines[:-1]):
        key = _match_label(ln)
        if not key or key in found:
            continue
        nxt = raw_lines[i + 1]
        if _match_label(nxt):
            continue
        if len(nxt) > 120:
            continue
        # serial: next baris tidak boleh label status (Yes/No/Activation…)
        if key == "serial":
            if re.match(r"^(yes|no|on|off|unlocked|locked)$", nxt.strip(), re.I):
                continue
            if re.search(r"activation|warranty|status|device|purchase", nxt, re.I):
                continue
        cleaned = _clean_value(key, nxt)
        if cleaned:
            found[key] = cleaned

    # 3) fallback IMEI 15 digit
    blob = " ".join(raw_lines)
    if "imei" not in found:
        m = re.search(r"\b(\d{15})\b", blob)
        if m:
            found["imei"] = m.group(1)
    if "imei2" not in found:
        imeis = re.findall(r"\b(\d{15})\b", blob)
        if len(imeis) >= 2:
            found["imei"] = found.get("imei") or imeis[0]
            found["imei2"] = imeis[1]

    # 4) serial: prioritaskan setelah label "Serial number"
    if "serial" not in found or not _normalize_serial_candidate(found.get("serial", "")):
        found.pop("serial", None)
        # cari pola Serial number ... VALUE di baris / baris berikut
        for i, ln in enumerate(raw_lines):
            if re.search(r"serial\s*number", ln, re.I):
                m = re.search(r"serial\s*number[:\s]+([A-Za-z0-9]{8,14})", ln, re.I)
                if m:
                    cand = _normalize_serial_candidate(m.group(1))
                    if cand:
                        found["serial"] = cand
                        break
                if i + 1 < len(raw_lines):
                    cand = _normalize_serial_candidate(raw_lines[i + 1])
                    if cand:
                        found["serial"] = cand
                        break
        if "serial" not in found:
            # fallback: token alnum 10-12 yang valid serial
            for tok in re.findall(r"\b([A-Z0-9]{10,12})\b", blob.upper()):
                cand = _normalize_serial_candidate(tok)
                if cand:
                    found["serial"] = cand
                    break

    # buang serial invalid
    if "serial" in found and not _normalize_serial_candidate(found["serial"]):
        found.pop("serial", None)

    if not found:
        return {}

    norm = imei_svc.normalize_device_info(found)
    norm["_provider"] = "screenshot_ocr"
    norm["_ocr_preview"] = "\n".join(raw_lines[:40])
    return norm


def process_screenshot(data: bytes) -> tuple[bool, dict[str, Any], str, str]:
    """
    Returns (ok, device_info, ocr_text, message).
    """
    ok, text, msg = image_bytes_to_text(data)
    if not ok:
        return False, {}, "", msg
    info = parse_imei_check_text(text)
    if not info or len([k for k in info if not k.startswith("_")]) < 1:
        return (
            False,
            {"_ocr_preview": text[:1500], "_provider": "screenshot_ocr"},
            text,
            "Teks terbaca tapi field belum terdeteksi. Coba crop hanya area hasil cek, atau isi manual.",
        )
    n = len([k for k in info if not str(k).startswith("_")])
    return True, info, text, f"Berhasil membaca ±{n} field dari screenshot. Mohon cek ulang sebelum simpan."


def process_screenshots(files: list[bytes]) -> tuple[bool, dict[str, Any], str, str]:
    """
    Proses beberapa screenshot (iUnlocker + IMEICheck), merge field termasuk IMEI/serial.
    """
    if not files:
        return False, {}, "", "Tidak ada file gambar."

    merged: dict[str, Any] = {}
    previews: list[str] = []
    any_ok = False
    messages: list[str] = []

    for i, data in enumerate(files, 1):
        if not data:
            continue
        ok, info, text, msg = process_screenshot(data)
        messages.append(f"Gambar {i}: {msg}")
        if text:
            previews.append(f"--- Gambar {i} ---\n{text[:800]}")
        if info:
            for k, v in info.items():
                if str(k).startswith("_"):
                    continue
                if v is None or v == "":
                    continue
                if k in ("imei", "imei2", "serial") and k in merged:
                    old, new = str(merged[k]), str(v)
                    if len(new) < len(old):
                        continue
                merged[k] = v
            if ok:
                any_ok = True

    if not merged and not previews:
        return False, {}, "", "; ".join(messages) or "Gagal membaca semua gambar."

    merged["_provider"] = "screenshot_ocr"
    merged["_ocr_preview"] = "\n\n".join(previews)[:2500]
    n = len([k for k in merged if not str(k).startswith("_")])
    if any_ok or n:
        return (
            True,
            merged,
            merged["_ocr_preview"],
            f"Merge {len(files)} screenshot → ±{n} field (IMEI/serial ikut jika terbaca). Cek ulang. "
            + (" | ".join(messages[:3])),
        )
    return False, merged, merged.get("_ocr_preview", ""), "; ".join(messages)

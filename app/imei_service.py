"""
Lookup IMEI / serial.

Tanpa API key: simpan manual + link ke situs cek eksternal.
Dengan env IMEI_API_URL + IMEI_API_KEY: coba fetch JSON (format fleksibel).
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any

import httpx

from .config import _clean_env


def clean_imei(value: str) -> str:
    return re.sub(r"\D", "", (value or "").strip())


def clean_serial(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", (value or "").strip()).upper()


def external_check_links(imei: str = "", serial: str = "") -> list[dict[str, str]]:
    """Tombol buka tab iUnlocker / IMEICheck (gratis di browser, isi manual di app)."""
    imei = clean_imei(imei)
    serial = clean_serial(serial)
    # Selalu sediakan 2 tombol utama
    if imei:
        iunlocker = f"https://iunlocker.com/check_imei.php?imei={imei}"
        imeicheck = f"https://imeicheck.com/id/cek-imei?imei={imei}"
    else:
        iunlocker = "https://iunlocker.com/"
        imeicheck = "https://imeicheck.com/id/cek-imei"
    links = [
        {"name": "Buka iUnlocker", "url": iunlocker, "id": "link-iunlocker"},
        {"name": "Buka IMEICheck", "url": imeicheck, "id": "link-imeicheck"},
    ]
    if serial and not imei:
        links[0]["url"] = "https://iunlocker.com/"
    return links


def normalize_device_info(raw: dict[str, Any]) -> dict[str, Any]:
    """Samakan key hasil API ke format app (mirip iUnlocker / imeicheck)."""
    # map berbagai nama field ke key standar
    aliases = {
        "model": ["model", "Model", "model_name", "modelName", "ModelDesc", "modelDesc", "title"],
        "model_number": ["model_number", "ModelNumber", "modelNumber", "ANumber"],
        "imei": ["imei", "IMEI", "IMEI1", "imei1"],
        "imei2": ["imei2", "IMEI2"],
        "meid": ["meid", "MEID"],
        "serial": ["serial", "Serial", "serial_number", "SerialNumber", "sn"],
        "color": ["color", "Colour", "warna"],
        "storage": ["storage", "capacity", "memory", "penyimpanan"],
        "sim_lock": ["sim_lock", "SimLock", "SimLockStatus", "simlock"],
        "fmi": ["fmi", "FindMyiPhone", "find_my", "icloud_lock"],
        "warranty": ["warranty", "WarrantyStatus", "WarrantyName", "warranty_status"],
        "purchase_date": ["purchase_date", "EstimatedPurchaseDate", "PurchaseDate", "purchaseDate"],
        "warranty_end": ["warranty_end", "EstimatedExpirationDate", "WarrantyExpired", "warranty_end"],
        "country": ["country", "CountryOfPurchase", "country_of_purchase", "ModelRegion"],
        "refurbished": ["refurbished", "Refurbished"],
        "demo": ["demo", "DemoUnit"],
        "replacement": ["replacement", "ReplacementDevice", "ReplacedDevice"],
        "activated": ["activated", "ActivationStatus", "PastFirstActivation"],
        "apple_care": ["apple_care", "AppleCare", "AppleCareEligible"],
        "region": ["region", "ModelRegion"],
        "sim_config": ["sim_config", "SIMConfig", "SimConfig"],
    }
    out: dict[str, Any] = {}
    lower_raw = {str(k).lower(): v for k, v in raw.items()}

    def pick(keys: list[str]):
        for k in keys:
            if k in raw and raw[k] not in (None, ""):
                return raw[k]
            if k.lower() in lower_raw and lower_raw[k.lower()] not in (None, ""):
                return lower_raw[k.lower()]
        return None

    for std, keys in aliases.items():
        val = pick(keys)
        if val is not None:
            out[std] = val

    # simpan sisa raw
    out["_raw"] = raw
    out["_checked_at"] = datetime.utcnow().isoformat() + "Z"
    return out


def lookup_imei_api(imei: str = "", serial: str = "") -> tuple[bool, dict[str, Any], str]:
    """
    Returns (ok, data, message).
    Butuh env:
      IMEI_API_URL  — URL endpoint (boleh {imei} placeholder)
      IMEI_API_KEY  — header/query key (opsional format di IMEI_API_KEY_HEADER)
    """
    api_url = _clean_env(os.environ.get("IMEI_API_URL"), "")
    api_key = _clean_env(os.environ.get("IMEI_API_KEY"), "")
    if not api_url:
        return (
            False,
            {},
            "API belum dikonfigurasi. Isi manual atau buka link cek eksternal. "
            "Set IMEI_API_URL (+ IMEI_API_KEY) di Railway untuk auto-lookup.",
        )

    q = clean_imei(imei) or clean_serial(serial)
    if not q:
        return False, {}, "IMEI atau serial wajib diisi."

    url = api_url.replace("{imei}", q).replace("{serial}", clean_serial(serial) or q)
    if "{imei}" not in api_url and "imei=" not in url.lower():
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}imei={q}"

    headers = {"Accept": "application/json", "User-Agent": "HP-Rekap/1.0"}
    key_header = _clean_env(os.environ.get("IMEI_API_KEY_HEADER"), "Authorization")
    if api_key:
        if key_header.lower() == "authorization" and not api_key.lower().startswith("bearer"):
            headers[key_header] = f"Bearer {api_key}"
        else:
            headers[key_header] = api_key

    try:
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            r = client.get(url, headers=headers)
        if r.status_code >= 400:
            return False, {}, f"API error HTTP {r.status_code}: {r.text[:200]}"
        data = r.json()
        if isinstance(data, dict) and "data" in data and isinstance(data["data"], dict):
            data = data["data"]
        if not isinstance(data, dict):
            return False, {}, "Format respons API tidak dikenali."
        norm = normalize_device_info(data)
        norm["_provider"] = _clean_env(os.environ.get("IMEI_API_PROVIDER"), "custom_api") or "custom_api"
        return True, norm, "Lookup berhasil."
    except Exception as e:
        return False, {}, f"Gagal menghubungi API: {e}"


def device_info_to_json(info: dict) -> str:
    return json.dumps(info, ensure_ascii=False, default=str)


def device_info_from_json(s: str | None) -> dict:
    if not s:
        return {}
    try:
        d = json.loads(s)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def build_manual_info(form: dict) -> dict[str, Any]:
    """Bangun device_info dari form manual (mirip hasil iUnlocker)."""
    fields = [
        "model",
        "model_number",
        "imei",
        "imei2",
        "meid",
        "serial",
        "color",
        "storage",
        "sim_lock",
        "fmi",
        "warranty",
        "purchase_date",
        "purchase_date_est",
        "warranty_end",
        "country",
        "refurbished",
        "demo",
        "replacement",
        "activated",
        "apple_care",
        "region",
        "sim_config",
    ]
    raw = {}
    for k in fields:
        v = (form.get(k) or "").strip()
        if not v:
            continue
        # form beli pakai purchase_date_est agar tidak bentrok tgl beli barang
        key = "purchase_date" if k == "purchase_date_est" else k
        raw[key] = v
    if not raw:
        return {}
    norm = normalize_device_info(raw)
    norm["_provider"] = "manual"
    return norm

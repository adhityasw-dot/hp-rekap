"""Konfigurasi dari environment (production-ready)."""
import os
import secrets
from pathlib import Path


def _clean_env(value: str | None, default: str = "") -> str:
    """Buang spasi & tanda kutip yang sering nempel di Variables Railway."""
    s = (value if value is not None else default) or ""
    s = str(s).strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        s = s[1:-1].strip()
    return s


# Root project
BASE_DIR = Path(__file__).resolve().parent.parent

# Data / SQLite — di Railway set DATA_DIR=/data
DATA_DIR = Path(_clean_env(os.environ.get("DATA_DIR"), str(BASE_DIR / "data")) or str(BASE_DIR / "data"))
try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    # fallback jika /data tidak writable
    DATA_DIR = BASE_DIR / "data"
    DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = Path(_clean_env(os.environ.get("DATABASE_PATH"), str(DATA_DIR / "hp_rekap.db")) or str(DATA_DIR / "hp_rekap.db"))

# Session signing key
_secret = _clean_env(os.environ.get("SECRET_KEY"), "")
if not _secret:
    secret_file = DATA_DIR / ".secret_key"
    if secret_file.exists():
        _secret = secret_file.read_text(encoding="utf-8").strip()
    if not _secret:
        _secret = secrets.token_hex(32)
        try:
            secret_file.write_text(_secret, encoding="utf-8")
        except OSError:
            pass
SECRET_KEY = _secret

# Login admin = isi Variables Railway (selalu)
ADMIN_USERNAME = _clean_env(os.environ.get("ADMIN_USERNAME"), "admin") or "admin"
ADMIN_PASSWORD = _clean_env(os.environ.get("ADMIN_PASSWORD"), "admin123") or "admin123"
ADMIN_DISPLAY = _clean_env(os.environ.get("ADMIN_DISPLAY"), "Admin") or "Admin"

# Cookie: default TIDAK secure dulu agar login tidak "hilang"
# Set COOKIE_SECURE=1 di Railway setelah login berhasil (opsional)
COOKIE_SECURE = _clean_env(os.environ.get("COOKIE_SECURE"), "0").lower() in (
    "1",
    "true",
    "yes",
)

HOST = _clean_env(os.environ.get("HOST"), "0.0.0.0") or "0.0.0.0"
PORT = int(_clean_env(os.environ.get("PORT"), "8000") or "8000")

# Katalog publik (link untuk konsumen) — ganti CATALOG_TOKEN di Railway
CATALOG_TOKEN = _clean_env(os.environ.get("CATALOG_TOKEN"), "leks-phone-katalog") or "leks-phone-katalog"
SHOP_WA = _clean_env(os.environ.get("SHOP_WA"), "085647377078") or "085647377078"
SHOP_IG = _clean_env(os.environ.get("SHOP_IG"), "aadhitsatriaa") or "aadhitsatriaa"
SHOP_TIKTOK = _clean_env(os.environ.get("SHOP_TIKTOK"), "aadhitsatriaa") or "aadhitsatriaa"
SHOP_NAME = _clean_env(os.environ.get("SHOP_NAME"), "Leks Phone") or "Leks Phone"
SHOP_TAGLINE = _clean_env(os.environ.get("SHOP_TAGLINE"), "Melayani Sepenuh Hati") or "Melayani Sepenuh Hati"
SHOP_AREA = _clean_env(os.environ.get("SHOP_AREA"), "Kirim se-Indonesia") or "Kirim se-Indonesia"

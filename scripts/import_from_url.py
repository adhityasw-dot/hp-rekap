"""
Coba unduh CSV publik dari Google Sheets lalu import.
Pemakaian:
  python scripts/import_from_url.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from app.database import Base, SessionLocal, engine
from app.main import import_csv_content, seed_if_needed

SHEET_ID = "18LzVzlXT0EUOjrE8hb23mANjCiBJSSGzXc-hXB2W4Cw"
# export format
URLS = [
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv",
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv",
]


def main():
    seed_if_needed()
    text = None
    for url in URLS:
        try:
            r = httpx.get(url, follow_redirects=True, timeout=30)
            if r.status_code == 200 and len(r.text) > 50:
                text = r.text
                print(f"OK unduh dari {url[:60]}... ({len(text)} chars)")
                break
            print(f"Gagal {r.status_code}: {url}")
        except Exception as e:
            print(f"Error {url}: {e}")
    if not text:
        print("Tidak bisa unduh. Export CSV manual lalu upload di /import")
        return
    db = SessionLocal()
    try:
        msg = import_csv_content(db, text, capital=50_000_000, snapshot_cash=True)
        print(msg)
    finally:
        db.close()


if __name__ == "__main__":
    main()

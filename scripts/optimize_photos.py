"""
Jalankan sekali untuk kompres foto lama (lokal / railway run):

  python scripts/optimize_photos.py

Atau lewat website (login): Import → Kompres semua foto lama
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import SessionLocal, ensure_schema  # noqa: E402
from app.media import reprocess_all_photos, rewrite_photo_json  # noqa: E402
from app.models import Item, ItemQcCheck  # noqa: E402


def main() -> None:
    ensure_schema()
    stats = reprocess_all_photos()
    path_map = stats.get("path_map") or {}
    db = SessionLocal()
    try:
        n_item = 0
        for item in db.query(Item).all():
            changed = False
            for attr in ("unit_photos_json", "threetools_photos_json"):
                raw = getattr(item, attr, None) or ""
                new_raw = rewrite_photo_json(raw, path_map)
                if new_raw is None and raw:
                    new_raw = rewrite_photo_json(raw, {})
                if new_raw is not None:
                    setattr(item, attr, new_raw)
                    changed = True
            if changed:
                n_item += 1
        n_qc = 0
        for qc in db.query(ItemQcCheck).all():
            raw = qc.photos_json or ""
            new_raw = rewrite_photo_json(raw, path_map)
            if new_raw is None and raw:
                new_raw = rewrite_photo_json(raw, {})
            if new_raw is not None:
                qc.photos_json = new_raw
                n_qc += 1
        db.commit()
    finally:
        db.close()

    mb = stats.get("bytes_saved", 0) / (1024 * 1024)
    print(
        f"OK processed={stats.get('processed')} scanned={stats.get('scanned')} "
        f"skipped={stats.get('skipped')} errors={stats.get('errors')} "
        f"saved_mb={mb:.2f} items={n_item} qc={n_qc}"
    )


if __name__ == "__main__":
    main()

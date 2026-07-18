"""Simpan foto QC / lampiran di DATA_DIR — otomatis resize + kompres."""
from __future__ import annotations

import io
import uuid
from pathlib import Path

from .config import DATA_DIR

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".heif"}

# Full image: jelas di HP, tapi tidak 5–12 MB
MAX_SIDE = 1600
JPEG_QUALITY = 82
# Thumbnail galeri: load cepat
THUMB_SIDE = 480
THUMB_QUALITY = 72


def _photos_root() -> Path:
    p = DATA_DIR / "qc_photos"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _optimize_image(
    data: bytes,
    *,
    max_side: int = MAX_SIDE,
    quality: int = JPEG_QUALITY,
) -> tuple[bytes, str] | None:
    """
    Resize (sisi terpanjang max_side) + simpan JPEG progressive.
    Perbaiki orientasi EXIF. Return (bytes, '.jpg') atau None jika gagal.
    """
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return None

    try:
        im = Image.open(io.BytesIO(data))
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "P", "LA"):
            background = Image.new("RGB", im.size, (255, 255, 255))
            if im.mode == "P":
                im = im.convert("RGBA")
            if im.mode in ("RGBA", "LA"):
                background.paste(im, mask=im.split()[-1])
                im = background
            else:
                im = im.convert("RGB")
        elif im.mode != "RGB":
            im = im.convert("RGB")

        w, h = im.size
        if max(w, h) > max_side:
            im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)

        buf = io.BytesIO()
        im.save(
            buf,
            format="JPEG",
            quality=quality,
            optimize=True,
            progressive=True,
        )
        return buf.getvalue(), ".jpg"
    except Exception:
        return None


def save_upload(
    data: bytes,
    filename: str = "",
    subdir: str = "misc",
    *,
    make_thumb: bool = True,
) -> str | None:
    """
    Simpan file (otomatis dikompres ke JPEG).
    Return relative path dari DATA_DIR (untuk URL /media/...).
    Thumbnail disimpan di samping: {name}_t.jpg (jika make_thumb).
    """
    if not data:
        return None

    folder = _photos_root() / subdir
    folder.mkdir(parents=True, exist_ok=True)
    stem = uuid.uuid4().hex

    optimized = _optimize_image(data, max_side=MAX_SIDE, quality=JPEG_QUALITY)
    if optimized:
        out_bytes, ext = optimized
    else:
        # fallback: simpan mentah (mis. file aneh)
        ext = Path(filename or "img.jpg").suffix.lower()
        if ext not in ALLOWED_EXT:
            ext = ".jpg"
        out_bytes = data

    name = f"{stem}{ext if optimized else ext}"
    if optimized:
        name = f"{stem}.jpg"
    path = folder / name
    path.write_bytes(out_bytes)

    if make_thumb and optimized:
        thumb = _optimize_image(data, max_side=THUMB_SIDE, quality=THUMB_QUALITY)
        if thumb:
            t_bytes, _ = thumb
            t_path = folder / f"{stem}_t.jpg"
            t_path.write_bytes(t_bytes)

    rel = path.relative_to(DATA_DIR).as_posix()
    return rel


def thumb_rel_path(rel_path: str) -> str | None:
    """Path thumbnail jika ada: foo/bar/abc.jpg → foo/bar/abc_t.jpg"""
    if not rel_path:
        return None
    p = Path(rel_path.replace("\\", "/"))
    # already a thumb
    if p.stem.endswith("_t"):
        return rel_path.replace("\\", "/")
    candidate = p.with_name(f"{p.stem}_t.jpg")
    full = DATA_DIR / candidate
    if full.is_file():
        return candidate.as_posix()
    return None


def ensure_thumb(rel_path: str) -> str:
    """
    Pastikan thumbnail ada; buat dari file full jika belum ada.
    Return path relative thumbnail (atau full jika gagal).
    """
    rel_path = (rel_path or "").replace("\\", "/").lstrip("/")
    if not rel_path:
        return rel_path
    existing = thumb_rel_path(rel_path)
    if existing:
        return existing
    full = DATA_DIR / rel_path
    if not full.is_file():
        return rel_path
    try:
        raw = full.read_bytes()
    except OSError:
        return rel_path
    thumb = _optimize_image(raw, max_side=THUMB_SIDE, quality=THUMB_QUALITY)
    if not thumb:
        return rel_path
    t_bytes, _ = thumb
    t_path = full.parent / f"{full.stem}_t.jpg"
    try:
        t_path.write_bytes(t_bytes)
        return t_path.relative_to(DATA_DIR).as_posix()
    except OSError:
        return rel_path


def media_url(rel_path: str) -> str:
    return f"/media/{rel_path.lstrip('/')}"


def media_urls(rel_path: str, *, ensure: bool = True) -> dict[str, str]:
    """url (penuh) + thumb_url (galeri). ensure=True buat thumb on-demand."""
    rel_path = (rel_path or "").replace("\\", "/")
    url = media_url(rel_path)
    if ensure:
        t = ensure_thumb(rel_path)
    else:
        t = thumb_rel_path(rel_path) or rel_path
    return {
        "url": url,
        "thumb_url": media_url(t) if t else url,
    }


def _draw_watermark(im) -> "Image.Image":
    """Tambah watermark LEKS PHONE (diagonal + pojok)."""
    from PIL import Image, ImageDraw, ImageFont

    if im.mode != "RGBA":
        base = im.convert("RGBA")
    else:
        base = im.copy()
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    text = "LEKS PHONE"
    w, h = base.size
    # ukuran font proporsional
    size = max(18, min(w, h) // 14)
    font = None
    for name in (
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ):
        try:
            font = ImageFont.truetype(name, size)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()

    # diagonal berulang
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        tw, th = size * 6, size
    step_x = tw + size * 2
    step_y = th + size * 3
    for y in range(-h // 4, h + step_y, step_y):
        for x in range(-w // 4, w + step_x, step_x):
            # tile text
            tile = Image.new("RGBA", (tw + 8, th + 8), (0, 0, 0, 0))
            td = ImageDraw.Draw(tile)
            td.text((2, 2), text, font=font, fill=(255, 255, 255, 48))
            rot = tile.rotate(30, expand=True, resample=Image.Resampling.BICUBIC)
            overlay.paste(rot, (x, y), rot)

    # pojok kanan bawah lebih tegas
    pad = max(8, size // 3)
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        tw, th = size * 6, size
    bx, by = w - tw - pad * 2, h - th - pad * 2
    draw.rectangle((bx - 4, by - 2, w - pad // 2, h - pad // 2), fill=(0, 0, 0, 90))
    draw.text((bx, by), text, font=font, fill=(232, 197, 71, 200))

    out = Image.alpha_composite(base, overlay).convert("RGB")
    return out


def ensure_watermarked(rel_path: str) -> str:
    """
    Buat salinan ber-watermark LEKS PHONE (cache di disk).
    Return path relative file watermark.
    """
    rel_path = (rel_path or "").replace("\\", "/").lstrip("/")
    if not rel_path:
        return rel_path
    p = Path(rel_path)
    if p.stem.endswith("_wm"):
        return rel_path
    # thumb watermark: name_t.jpg → name_t_wm.jpg
    wm_name = f"{p.stem}_wm.jpg"
    wm_rel = (p.parent / wm_name).as_posix()
    wm_full = DATA_DIR / wm_rel
    src_full = DATA_DIR / rel_path
    if not src_full.is_file():
        return rel_path
    if wm_full.is_file() and wm_full.stat().st_mtime >= src_full.stat().st_mtime:
        return wm_rel
    try:
        from PIL import Image, ImageOps

        im = Image.open(src_full)
        im = ImageOps.exif_transpose(im)
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGB")
        wm = _draw_watermark(im)
        wm_full.parent.mkdir(parents=True, exist_ok=True)
        wm.save(wm_full, format="JPEG", quality=82, optimize=True, progressive=True)
        return wm_rel
    except Exception:
        return rel_path


def _is_main_image(path: Path) -> bool:
    if not path.is_file():
        return False
    if path.stem.endswith("_t"):
        return False
    return path.suffix.lower() in ALLOWED_EXT or path.suffix.lower() in {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".gif",
        ".bmp",
    }


def reprocess_file(path: Path) -> tuple[str | None, str | None, int]:
    """
    Kompres 1 file di disk.
    Return (old_rel or None, new_rel, bytes_saved).
    old_rel diisi jika path berubah (mis. .png → .jpg) supaya DB bisa di-update.
    """
    if not _is_main_image(path):
        return None, None, 0
    try:
        raw = path.read_bytes()
    except OSError:
        return None, None, 0
    old_size = len(raw)
    if old_size < 8:
        return None, None, 0

    opt = _optimize_image(raw, max_side=MAX_SIDE, quality=JPEG_QUALITY)
    if not opt:
        return None, None, 0
    out_bytes, _ = opt

    thumb_path = path.parent / f"{path.stem}_t.jpg"
    already_jpg = path.suffix.lower() in (".jpg", ".jpeg")
    # Cek dimensi — file kecil tapi resolusi tinggi tetap di-resize
    need_resize = False
    try:
        from PIL import Image

        with Image.open(path) as im:
            need_resize = max(im.size) > MAX_SIDE
    except Exception:
        need_resize = old_size > 200_000

    already_ok = (
        already_jpg
        and not need_resize
        and old_size < 280_000
        and old_size <= len(out_bytes) * 1.15
        and thumb_path.is_file()
        and thumb_path.stat().st_size > 500
    )
    if already_ok:
        return None, path.relative_to(DATA_DIR).as_posix(), 0

    new_path = path.with_suffix(".jpg")
    try:
        new_path.write_bytes(out_bytes)
    except OSError:
        return None, None, 0

    # Selalu (re)buat thumbnail
    thumb = _optimize_image(raw, max_side=THUMB_SIDE, quality=THUMB_QUALITY)
    if thumb:
        try:
            (new_path.parent / f"{new_path.stem}_t.jpg").write_bytes(thumb[0])
        except OSError:
            pass

    old_rel = path.relative_to(DATA_DIR).as_posix()
    new_rel = new_path.relative_to(DATA_DIR).as_posix()
    saved = max(0, old_size - len(out_bytes))

    if path.resolve() != new_path.resolve() and path.exists():
        try:
            path.unlink()
        except OSError:
            pass
        return old_rel, new_rel, saved

    return None, new_rel, saved


def reprocess_all_photos() -> dict:
    """
    Kompres semua foto di DATA_DIR/qc_photos.
    Return statistik + path_map {old_rel: new_rel} untuk update DB.
    """
    root = _photos_root()
    stats = {
        "scanned": 0,
        "processed": 0,
        "skipped": 0,
        "errors": 0,
        "bytes_saved": 0,
        "path_map": {},
    }
    if not root.is_dir():
        return stats

    for path in sorted(root.rglob("*")):
        if not _is_main_image(path):
            continue
        stats["scanned"] += 1
        try:
            old_rel, new_rel, saved = reprocess_file(path)
        except Exception:
            stats["errors"] += 1
            continue
        if new_rel is None and old_rel is None:
            stats["errors"] += 1
            continue
        if saved == 0 and old_rel is None:
            stats["skipped"] += 1
            continue
        stats["processed"] += 1
        stats["bytes_saved"] += saved
        if old_rel and new_rel and old_rel != new_rel:
            stats["path_map"][old_rel] = new_rel
    return stats


def rewrite_photo_json(raw: str | None, path_map: dict[str, str]) -> str | None:
    """Update path/url di JSON list foto setelah rename file."""
    import json

    if not raw or not path_map:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    if not isinstance(data, list):
        return None
    changed = False
    for p in data:
        if not isinstance(p, dict):
            continue
        path = (p.get("path") or "").replace("\\", "/")
        if path in path_map:
            new_path = path_map[path]
            p["path"] = new_path
            urls = media_urls(new_path)
            p["url"] = urls["url"]
            p["thumb_url"] = urls["thumb_url"]
            changed = True
        elif path:
            # pastikan thumb_url terisi meski path sama
            urls = media_urls(path)
            if p.get("thumb_url") != urls["thumb_url"] or p.get("url") != urls["url"]:
                p["url"] = urls["url"]
                p["thumb_url"] = urls["thumb_url"]
                changed = True
    if not changed:
        return None
    return json.dumps(data, ensure_ascii=False)

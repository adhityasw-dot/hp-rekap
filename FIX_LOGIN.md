# Perbaikan login Railway — update 2 file di GitHub

## File 1: `app/main.py`

Cari fungsi `seed_if_needed` dan `login_post` serta `health`.

Ganti **seluruh** fungsi `seed_if_needed` menjadi:

```python
def seed_if_needed():
    """
    Pastikan user admin selalu cocok dengan Variables Railway.
    Mode 1 akun: setiap start, password admin diset ulang dari ADMIN_PASSWORD.
    """
    import logging

    log = logging.getLogger("hp-rekap")
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
        log.warning(
            "Admin ready: username=%r password_len=%s",
            ADMIN_USERNAME,
            len(ADMIN_PASSWORD or ""),
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
```

Pastikan di atas file ada import:
```python
from .config import ADMIN_DISPLAY, ADMIN_PASSWORD, ADMIN_USERNAME, DB_PATH
```

Ganti **seluruh** `login_post` menjadi:

```python
@app.post("/login")
def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    uname = (username or "").strip()
    pwd = (password or "").strip()
    seed_if_needed()
    db.expire_all()
    user = db.query(User).filter(User.username == uname).first()
    if not user or not verify_password(pwd, user.password_hash):
        n = db.query(User).count()
        names = [u.username for u in db.query(User).all()]
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "user": None,
                "flash_ok": None,
                "flash_err": (
                    "Username atau password salah. "
                    f"Pakai nilai Railway Variables ADMIN_USERNAME / ADMIN_PASSWORD. "
                    f"(user di server: {names or 'kosong'}, total={n})"
                ),
            },
        )
    resp = RedirectResponse("/", status_code=303)
    set_login_cookie(resp, user.username)
    return resp
```

Ganti `health`:

```python
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
```

Commit → tunggu Railway redeploy Success.

## Login setelah redeploy

```
username: admin
password: leksphone
```

(sesuai Variables Anda)

## Cek

Buka: `https://URL-ANDA/health`  
Harus ada `"users":["admin"]` dan `"admin_env":"admin"`.

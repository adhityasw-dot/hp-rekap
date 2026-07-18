# Deploy HP Rekap Online (akses di mana saja)

Setelah deploy, Anda **tidak perlu** menjalankan `python run.py` di PC.

## Opsi termudah: Railway (disarankan)

### 1. Buat akun
Buka: https://railway.app  
Login dengan **Google** / GitHub (gratis).

### 2. Deploy dari GitHub (paling stabil)

1. Buat repo GitHub baru (public atau private), upload folder project ini  
   **atau** push repo lokal yang sudah di-commit.
2. Di Railway: **New Project → Deploy from GitHub repo**
3. Pilih repo `hp-rekap`
4. Railway mendeteksi **Dockerfile** otomatis

### 3. Variable environment (penting)

Di Railway → service → **Variables**, tambahkan:

| Nama | Nilai contoh |
|------|----------------|
| `ENV` | `production` |
| `DATA_DIR` | `/data` |
| `SECRET_KEY` | string acak panjang (klik Generate) |
| `ADMIN_USERNAME` | `admin` |
| `ADMIN_PASSWORD` | **password kuat Anda** |
| `COOKIE_SECURE` | `1` |

### 4. Volume (agar data tidak hilang)

**Jangan** mengandalkan `VOLUME` di Dockerfile (Railway menolak build).

Di dashboard Railway → service → **Settings → Volumes** (atau **+ New → Volume**):
- Mount path: `/data`
- Supaya database SQLite tetap ada setelah restart

### 5. Domain

Railway → **Settings → Networking → Generate Domain**  
Contoh: `https://hp-rekap-production.up.railway.app`

### 6. Login app

Buka domain → login dengan `ADMIN_USERNAME` / `ADMIN_PASSWORD`  
Lalu **Import** data dari Google Sheets (menu Import).

---

## Alternatif: Render (gratis, bisa “tidur” jika jarang dipakai)

1. https://render.com → New → **Blueprint**  
2. Hubungkan repo yang berisi `render.yaml`  
3. Deploy  
4. Catatan: paket free bisa **sleep** setelah idle → request pertama lambat

---

## Setelah online

| Tugas | Cara |
|--------|------|
| Akses kapan saja | Buka URL HTTPS dari HP/laptop |
| Teman bantu input | Beri URL + login (atau buat user baru nanti) |
| Data lama | Menu **Import → Import dari Google Sheets** |
| Backup | Download / export berkala (fitur export bisa ditambah) |

---

## Keamanan

- Ganti password default segera  
- Jangan share password di chat publik  
- Link app bersifat private lewat login, tapi URL bisa ditebak — password harus kuat

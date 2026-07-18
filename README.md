# HP Rekap — Web App Jual-Beli Handphone

Aplikasi web sederhana untuk stok unit, penjualan, laba per unit, kas (1 kantong), pengeluaran operasional, dan laporan bulanan.

## A. Desain (Skema + Alur)

### Pengguna
- Login username + password (sama untuk owner & helper — akses penuh semua fitur).
- Default seed: `admin` / `admin123` (ganti setelah login pertama).

### Skema database

| Tabel | Fungsi |
|--------|--------|
| `users` | Akun login |
| `items` | Stok unit / aksesoris (beli, status ready/sold, harga jual) |
| `item_costs` | Biaya tambahan per unit (service, baterai, ongkir, dll.) |
| `cash_entries` | Buku kas 1 kantong (masuk/keluar) |
| `operational_expenses` | Pengeluaran operasional bulanan (sewa, bensin, dll.) |

**Item**
- `kind`: `unit` (HP/laptop 1 pcs) atau `bulk` (charger, case, qty)
- `status`: `ready` | `sold` | `partial` (bulk terjual sebagian)
- Laba unit = harga jual − harga beli − sum(item_costs)

**Kas**
- Tipe: `capital`, `purchase`, `sale`, `operational`, `withdraw`, `adjust`
- Saldo kas = sum(masuk) − sum(keluar)

**Modal di barang** = total harga beli stok yang masih `ready` (proporsional sisa qty untuk bulk)

### Alur layar

```
Login
  └─ Dashboard          → kas, modal di barang, laba bulan ini, stok ready, alert mengendap
  └─ Stok Ready         → daftar unit belum laku + filter
  └─ Beli Barang        → form beli → stok + + kas −
  └─ Jual Barang        → pilih stok → harga jual → stok sold + kas +
  └─ Detail Item        → biaya tambahan, edit catatan, riwayat
  └─ Kas                → buku kas + setor modal / tarik / penyesuaian
  └─ Operasional        → pengeluaran bulanan (ikut kurangi kas)
  └─ Laporan            → laba, omzet, operasional per bulan
  └─ Import             → upload CSV dari spreadsheet lama
```

### Hosting online (nanti)
- Deploy ke Railway / Render / VPS + domain
- Ganti SQLite → PostgreSQL jika perlu
- HTTPS wajib

## B. Menjalankan lokal

```powershell
cd C:\Users\Leks\Documents\hp-rekap
python -m pip install -r requirements.txt
python run.py
```

Buka: http://127.0.0.1:8000  
Login: `admin` / `admin123`

### Import spreadsheet
1. Di Google Sheets: **File → Unduh → CSV** (sheet rekap utama)
2. Menu **Import** di app → upload file
3. Isi modal awal (mis. 50000000) jika diminta
4. Lengkapi **harga jual** untuk unit yang sudah sold (agar laba akurat)

## Struktur folder

```
hp-rekap/
  app/           # aplikasi FastAPI
  data/          # SQLite (hp_rekap.db)
  scripts/       # utilitas
  run.py
  requirements.txt
```

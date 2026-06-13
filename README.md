# 🐄 MooOS — Sistem Manajemen Ternak Koperasi Harapan Baru

MooOS adalah platform manajemen peternakan sapi berbasis web yang terintegrasi dengan **Telegram Bot** untuk otomasi pencatatan harian. Dibangun untuk **Koperasi Harapan Baru** dengan skema bagi hasil 60% koperasi / 40% pemilik sapi.

## 📋 Fitur Utama

| Modul | Deskripsi |
|-------|-----------|
| **Dashboard** | Ringkasan metrik ternak, keuangan, dan notifikasi |
| **Anggota** | Manajemen 20 penitip + 2 penanggungjawab |
| **Ternak** | Data 30 sapi: bobot, usia, jenis, status, QR code |
| **Hasil Produksi** | Tracking susu harian/mingguan/bulanan + auto-save MRP |
| **Manajemen Pakan** | Rekomendasi order, tren harga, pembagian per kandang |
| **Limbah & Pupuk** | Fermentasi kotoran → pupuk organik (14 hari) |
| **Transaksi** | Arus kas, riwayat, filter & export CSV |
| **Laporan** | Analisis keuangan 60/40, unduh PDF |
| **Telegram Bot** | Lapor pakan/susu/limbah/sakit per kandang |

## 🏗️ Arsitektur

```
┌───────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Frontend    │────▶│   FastAPI Backend │◀────│  Telegram Bot   │
│  (HTML/JS/    │     │   (Python 3.x)   │     │  (pyTeleBot)    │
│  TailwindCSS) │     │                  │     │                 │
└───────────────┘     └────────┬─────────┘     └─────────────────┘
                               │
                      ┌────────▼─────────┐
                      │   SQLite + ORM   │
                      │  (SQLAlchemy)    │
                      └──────────────────┘
```

## 💰 Model Keuangan

- **Simpanan Pokok**: Rp 1.500.000 / anggota (sekali seumur hidup)
- **Simpanan Wajib**: Rp 200.000 / sapi / bulan
- **Bagi Hasil**: 60% koperasi, 40% pemilik sapi
- **Pekerja**: 5 orang (2 kandang A, 2 kandang B, 1 admin) @ Rp 3.800.000

## 🚀 Setup & Instalasi

### Prerequisites
- **Node.js** (v16+)
- **Python** (3.9+)
- **pip**

### 1. Clone & Install Frontend
```bash
git clone <repository-url>
cd Enterteamname_Hackathon_TS9
npm install
```

### 2. Setup Backend
```bash
cd backend
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate

pip install fastapi uvicorn sqlalchemy python-dotenv pytelegrambotapi qrcode pillow
```

### 3. Konfigurasi Environment
Buat file `backend/.env`:
```env
API_TOKEN=your_telegram_bot_token
BOT_USERNAME=your_bot_username
ABYASA_ID=telegram_id_kandang_a
AXEL_ID=telegram_id_kandang_b
ELISA_ID=telegram_id_supplier_1
RAFIF_ID=telegram_id_supplier_2
```

### 4. Jalankan
```bash
# Terminal 1 — Backend
cd backend
python main.py
# Server berjalan di http://localhost:8000

# Terminal 2 — Frontend
npm run start
# Dev server berjalan di http://localhost:3000
```

## 📱 Telegram Bot Commands

| Command | Fungsi |
|---------|--------|
| `/start` | Registrasi & deep-link QR scan |
| `/lapor` | Menu laporan harian kandang |

### Menu `/lapor`:
- 🌾 **Selesai Beri Pakan** — Catat pemberian pakan
- 🥛 **Selesai Perah Susu** — Input liter susu per sapi
- 💩 **Selesai Kumpul Limbah** — Catat pengumpulan limbah harian
- 🩺 **Lapor Sapi Sakit/Mati** — Laporan kesehatan

## 📁 Struktur Proyek

```
├── backend/
│   ├── .env              # Secrets (tidak di-commit)
│   ├── main.py           # FastAPI server + routes
│   ├── models.py         # SQLAlchemy ORM models
│   ├── database.py       # DB init + seed data
│   ├── financials.py     # MRP logic (Feed/Milk/Waste/Ops)
│   ├── config.py         # Env-based configuration
│   └── telegram_bot.py   # Telegram bot handlers
│
├── src/
│   ├── dashboard_MooOS.html
│   ├── anggota_MooOS.html
│   ├── ternak_MooOS.html
│   ├── hasil_MooOS.html
│   ├── pakan_MooOS.html
│   ├── limbah_MooOS.html
│   ├── transaksi_MooOS.html
│   ├── laporan_MooOS.html
│   ├── pengaturan_MooOS.html
│   ├── bantuan_MooOS.html
│   ├── js/
│   │   └── toast.js      # Toast notification system
│   └── partials/
│       ├── sidebar.html
│       └── header.html
│
├── webpack.config.js
├── package.json
└── README.md
```

## 🧪 API Endpoints

| Method | Path | Deskripsi |
|--------|------|-----------|
| GET | `/cows` | Daftar semua sapi |
| GET | `/members` | Daftar semua anggota |
| GET | `/milk/summary` | Ringkasan produksi susu |
| POST | `/milk/financials` | Simpan data MRP susu |
| GET | `/api/financials/feed` | Data pakan (chart + metrik) |
| GET | `/api/financials/waste` | Data limbah/pupuk |
| GET | `/api/financials/report?period=30` | Laporan keuangan agregat |
| GET | `/reports/{type}/pdf?period=30` | Download laporan PDF |
| GET | `/api/config` | Konfigurasi koperasi |

## 👥 Tim

**Enter Team Name** — Hackathon TS9

---

> ⚠️ **Catatan**: Jangan commit file `.env` ke repository. Gunakan `.env.example` sebagai template.

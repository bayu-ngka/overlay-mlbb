# Mobile Legends: Bang Bang (MLBB) Esports Broadcast Overlay & Control Hub

Aplikasi broadcast overlay profesional untuk turnamen Mobile Legends: Bang Bang (MLBB) bertema Golkar Esports dengan arsitektur **Single Source of Truth** (WebSocket Real-time Sync).

---

## 🚀 Fitur Utama
1. **Control Hub Interaktif (`/control.html`)**:
   - **PRE-MATCH**: Pengaturan nama & singkatan tim (Swap tim), series score (BO1, BO3, BO5), pemilihan arena map, dan emergency timer cutout.
   - **BAN / PICK**: Antarmuka draft resmi MLBB dengan tab filter role (Tank, Fighter, Assassin, Mage, Marksman, Support), pencarian nama hero, dan galeri foto portrait lengkap (133 hero termasuk hero terbaru: *Hirara, Suyou, Zhuxin, Lukas, Sora, Marcel, Kalea*).
   - **Double Pick Fleksibel**: Memungkinkan operator memilih dan mengunci hero pemain mana saja terlebih dahulu (misal: Pemain 3 sebelum Pemain 2) tanpa memakan tempat atau membuat layout melebar.
   - **No-Leak Preview**: Pemilihan hero oleh operator tidak akan pernah bocor ke tampilan live OBS sebelum tombol **LOCK** ditekan.
   - **Sistem Koreksi Hero**: Klik slot manapun pada papan monitor untuk mengubah hero yang salah pilih via pop-up visual dialog.
   - **Esports Confirmation Modal**: Dialog konfirmasi kustom bertema esports tanpa menggunakan alert browser kaku.
   - **Menu SETTINGS**: Pengaturan dinamis alamat link JSON engine OCR in-game lengkap dengan fitur **Live Ping Test**.

2. **Overlay Ban & Pick OBS (`/bp1.html`)**:
   - Resolusi 1920x1080 (bottom-anchored canvas).
   - Kotak ban bersih di atas (tanda silang otomatis hilang saat hero di-ban).
   - Indikator garis bawah merah menyala pada player yang bertugas melakukan ban.
   - Animasi rotasi sponsor terpusat dan tersinkronisasi.

3. **Overlay Scoreboard OBS (`/sb1.html`)**:
   - Integrasi OCR in-game (Gold, Kill, Lord, Turtle, Turret, Timer).
   - Smart timer ticker independen dengan proteksi drift resync.

---

## 📦 Cara Memasang & Menjalankan di PC Baru

### Prasyarat
- **Node.js** (versi 18.x atau yang lebih baru). Unduh di: [nodejs.org](https://nodejs.org)
- **Git** (opsional untuk clone repositori).
- **OBS Studio** untuk menampilkan overlay siaran.

---

### Cara Paling Mudah di Windows (1 Klik)
Cukup **klik dua kali (double click) file `start_server.bat`** di folder utama proyek!
- Script `.bat` akan otomatis memeriksa apakah **Node.js** sudah terpasang.
- Jika Node.js belum ada, script akan memberi petunjuk unduh langsung ke situs resminya.
- Script akan memeriksa apakah paket `node_modules` (express, cors, ws) sudah lengkap. Jika belum, script otomatis menjalankan `npm install`.
- Setelah itu, server langsung aktif di port 8055 dan halaman **Control Hub** otomatis terbuka di browser Anda.

---

### Langkah-langkah Manual (Command Line)

#### 1. Clone atau Salin Folder Proyek
Buka terminal / Command Prompt (CMD / PowerShell):
```bash
git clone git@github.com:bayu-ngka/overlay-mlbb.git
cd overlay-mlbb/backend
```
*(Atau jika menyalin file zip/folder, buka folder `overlay/backend`)*

#### 2. Install Dependensi Node.js
Jalankan perintah berikut di dalam folder `backend`:
```bash
npm install
```

#### 3. Jalankan Server
```bash
node server.js
```
Jika berhasil, akan muncul output:
```text
=======================================================
🚀 ESPORT OVERLAY SERVER AKTIF DI PORT: 8055
📡 Localhost : http://localhost:8055/control.html
🌐 Akses LAN  : http://[IP-KOMPUTER]:8055/control.html
=======================================================
```

---

## 🖥️ URL Akses & Penggunaan

| Halaman | URL Lokal | Keterangan |
| :--- | :--- | :--- |
| **Control Hub** | `http://localhost:8055/control.html` | Buka di browser admin / operator turnamen. |
| **Overlay Ban & Pick** | `http://localhost:8055/bp1.html` | Tambahkan sebagai **Browser Source** di OBS (Ukuran: 1920 x 1080). |
| **Overlay Scoreboard** | `http://localhost:8055/sb1.html` | Tambahkan sebagai **Browser Source** di OBS (Ukuran: 1920 x 1080). |

---

## ⚙️ Menghubungkan OCR Game In-Game
1. Buka Control Hub di browser: `http://localhost:8055/control.html`.
2. Klik menu **SETTINGS** di sidebar sebelah kiri.
3. Masukkan URL endpoint OCR Anda (contoh: `http://192.168.1.100:14337/MLBB.json` atau `http://localhost:14337/MLBB.json`).
4. Klik **SIMPAN LINK OCR**.
5. Klik **⚡ TEST KONEKSI SEKARANG** untuk memverifikasi apakah data JSON OCR dapat dibaca dengan sukses oleh server overlay.

---

## 🌐 Menjalankan Melalui Jaringan LAN (PC Operator & PC OBS Berbeda)
Jika PC Operator Control Hub berbeda dengan PC OBS:
1. Cari IP Address PC tempat server `server.js` berjalan (misal: `192.168.1.50`).
2. Di PC Operator, buka browser: `http://192.168.1.50:8055/control.html`.
3. Di PC OBS, masukkan URL Browser Source: `http://192.168.1.50:8055/bp1.html` atau `http://192.168.1.50:8055/sb1.html`.

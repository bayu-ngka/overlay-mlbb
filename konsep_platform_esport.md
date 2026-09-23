# Konsep Platform Manajemen Turnamen & Broadcast Overlay Esports

## 1. Visi & Deskripsi Proyek
Membangun platform "All-in-One" berbasis Cloud (Online) yang menggabungkan **Sistem Manajemen Turnamen** (seperti Challonge/Battlefy) dengan **Sistem Broadcast Overlay** profesional (setara standar MPL ID). 

Sistem ini didesain agar mudah digunakan oleh Event Organizer (EO) turnamen kelas komunitas/café hingga profesional, tanpa memerlukan PC spesifikasi tinggi atau setup lokal yang rumit.

**Pilot Project:** Mobile Legends: Bang Bang (MLBB).

---

## 2. Arsitektur Sistem Utama (Online & Real-Time)

Karena sistem ini sepenuhnya online, komunikasi data sekecil apa pun harus cepat dan sinkron di semua layar (Operator, Caster, Peserta, dan Layar Live Streaming/OBS).

* **Backend & API:** Node.js (Express/NestJS) atau Laravel. Berfungsi mengatur database (User, Turnamen, Match, Roster).
* **Real-time Engine (WebSockets):** Menggunakan Socket.IO atau Laravel WebSockets. Berfungsi meneruskan *trigger* dari Control Panel ke OBS Overlay secara instan (delay < 1 detik).
* **Frontend Dashboard:** Vue.js atau React.js. Untuk portal peserta, panel admin EO, dan antarmuka Control Panel Caster.
* **Overlay Engine:** Template HTML/CSS/JS dinamis yang di-render di browser source OBS. Data diambil via WebSocket (`/overlay/{room_id}/draft`).

---

## 3. Fitur Utama & Modul (Pilot: MLBB)

### A. Manajemen Pertandingan (Tournament Engine)
1. **Registrasi Tim:** Form pendaftaran online (Nama Tim, Logo, Nickname, ID).
2. **Manajemen Bagan (Bracket):**
   * Generator bagan otomatis (Single Elimination, Double Elimination).
   * Fitur "Acak Bagan" (Shuffle Seed).
   * Update bagan otomatis setelah match di overlay selesai.
3. **Database Tim & Roster:** Penyimpanan otomatis logo tim dan foto pemain agar siap dipanggil kapan saja saat siaran.

### B. Modul Overlay Standar MPL ID
Modul-modul ini dirender terpisah menggunakan URL spesifik di OBS (contoh: `domain.id/obs/{room_id}/draft`).
1. **Map Draw / Acak Map:** Animasi visual pengundian map (jika menggunakan sistem turnamen khusus, atau sekadar penentuan sisi Blue/Red).
2. **Drafting Phase (Pick & Ban):** 
   * Tema ala MPL ID (Elegan, timer presisi, efek glow pada hero pick/ban).
   * Mendukung format standar dan 6 bans.
   * Menampilkan foto pemain (Mugshot), nama asli, dan *role* (Jungler, Roamer, dll).
3. **In-Game Scoreboard:** 
   * Menggunakan OCR Relay (Data dari PC In-game dikirim ke cloud via WebSocket, lalu di-push ke OBS).
   * Tampilan Lord, Turtle, Turret, Gold, Kill Score.
4. **Post-Match & MVP:** 
   * Grafik statistik Damage/Gold, KDA.
   * Penobatan MVP dengan efek transisi mewah.

### C. Kontrol Overlay (Control Panel Caster/Admin)
Halaman web khusus untuk operator siaran. Operator tidak perlu mengetik nama tim dari awal.
1. **Match Selector:** Pilih match dari bagan, data (Tim A vs Tim B, Logo, Skor BO3) langsung termuat.
2. **Draft Controller:** Tombol untuk lock hero ban/pick, set timer, ganti fase.
3. **Scene Switcher Sync (Opsional):** Tombol di web untuk mengubah scene di OBS secara langsung via OBS WebSocket.

---

## 4. Alur Kerja (Workflow) yang Jelas

**Tahap 1: Setup Turnamen (H-1)**
1. Panitia membuat turnamen di platform.
2. Peserta mendaftar via link.
3. Panitia menutup pendaftaran dan menekan tombol **"Acak Bagan"**. Bagan rilis ke publik.

**Tahap 2: Persiapan Siaran (Hari H)**
1. Operator membuka OBS.
2. Operator memasukkan Link Browser Source (mendapatkan Token Room khusus turnamen tersebut).
3. Operator membuka **Control Panel** di web platform (bisa dari laptop terpisah / HP).

**Tahap 3: Siklus Pertandingan (Live Stream)**
1. Operator memilih *Match 1 (Tim X vs Tim Y)* di Control Panel. Overlay OBS otomatis memperbarui logo dan nama tim.
2. **Animasi Side Coin Toss / Map Draw** dijalankan dari panel.
3. Masuk **Drafting Phase**. Operator mengontrol timer dan lock hero dari tablet/PC-nya. Overlay di OBS berjalan mulus (WebSocket).
4. Masuk **In-Game**. Scoreboard aktif mengambil data (via manual klik atau integrasi OCR lokal yang mem-push ke server cloud).
5. Match selesai. Operator menekan tombol **"Tim X Menang"**.
6. Animasi **MVP** ditampilkan.
7. **Sistem otomatis meng-update Bagan Turnamen** publik (Tim X maju ke babak selanjutnya). Siklus berulang ke Match 2.

---

## 5. Roadmap Pengembangan (Langkah Kerja Teknis)

**Langkah 1: Setup Fondasi Repositori (Minggu 1)**
* Setup struktur folder `backend/` dan `frontend/`.
* Penentuan struktur Database (Tabel User, Tournament, Match, Participant).

**Langkah 2: Core Real-Time Engine (Minggu 2)**
* Membangun server WebSocket.
* Membuat sistem Room ID (`socket.join(roomId)`) agar data antar turnamen tidak tertukar.
* Tes pengiriman pesan dari halaman Control Dummy ke halaman Overlay Dummy.

**Langkah 3: Migrasi & Peningkatan Visual Overlay MLBB (Minggu 3-4)**
* Memindahkan aset HTML/CSS dari project lama (`referensi/`) ke sistem dinamis di Frontend (React/Vue).
* Membuat tampilan Draft Pick dan In-Game Scoreboard dengan referensi desain MPL ID yang lebih responsif dan *clean*.

**Langkah 4: Membangun Control Panel (Minggu 5)**
* Membuat antarmuka untuk Operator.
* Menghubungkan tombol-tombol panel dengan aksi di overlay (Trigger animasi, ubah teks, ganti gambar).

**Langkah 5: Sistem Manajemen Turnamen (Minggu 6-7)**
* Membuat alur registrasi, pembuatan *Bracket* Single/Double Elimination.
* Menghubungkan data *Bracket* ke Control Panel (agar data tim otomatis masuk ke overlay).

**Langkah 6: Testing, OCR Bridge & Deployment (Minggu 8)**
* Membuat *agent script* kecil untuk jembatan OCR lokal ke Cloud.
* Uji coba End-to-End dengan turnamen skala kecil (Alpha Testing).
* Rilis Beta.

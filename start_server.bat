@echo off
setlocal enabledelayedexpansion
title MLBB Esports Overlay Server Launcher

echo ========================================================
echo   MLBB ESPORTS BROADCAST OVERLAY - WINDOWS LAUNCHER
echo ========================================================
echo.

:: 1. Cek instalasi Node.js
where node >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Node.js TIDAK DITEMUKAN pada sistem ini!
    echo.
    echo Silakan unduh dan pasang Node.js (versi 18 ke atas) dari:
    echo https://nodejs.org/
    echo.
    echo Setelah menginstal Node.js, tutup dan buka kembali jendela ini.
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%v in ('node -v 2^>nul') do set NODE_VERSION=%%v
echo [OK] Node.js terdeteksi: %NODE_VERSION%

:: 2. Cek instalasi npm
where npm >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] npm (Node Package Manager) tidak ditemukan!
    echo Pastikan opsi 'npm package manager' dicentang saat menginstal Node.js.
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%v in ('npm -v 2^>nul') do set NPM_VERSION=%%v
echo [OK] npm terdeteksi: v%NPM_VERSION%
echo.

:: 3. Pindah ke direktori backend (tempat server.js dan package.json berada)
if exist "%~dp0backend\server.js" (
    cd /d "%~dp0backend"
) else if exist "%~dp0server.js" (
    cd /d "%~dp0"
) else (
    echo [ERROR] File 'server.js' tidak ditemukan di folder proyek ini!
    echo Pastikan file start_server.bat berada di root folder overlay-mlbb.
    echo.
    pause
    exit /b 1
)

:: 4. Cek folder node_modules dan dependensi yang dibutuhkan
set NEED_INSTALL=0
if not exist "node_modules\" (
    set NEED_INSTALL=1
    echo [INFO] Folder 'node_modules' belum ada. Menginstal dependensi...
) else (
    :: Cek paket-paket esensial
    if not exist "node_modules\express\" set NEED_INSTALL=1
    if not exist "node_modules\cors\" set NEED_INSTALL=1
    if not exist "node_modules\ws\" set NEED_INSTALL=1
)

if %NEED_INSTALL% equ 1 (
    echo ========================================================
    echo   MENGINSTAL DEPENDENSI YANG DIBUTUHKAN...
    echo   (express, cors, ws)
    echo ========================================================
    echo.
    call npm install
    if %errorlevel% neq 0 (
        echo.
        echo [ERROR] Gagal menginstal dependensi melalui npm!
        echo Pastikan komputer terhubung ke internet dan coba jalankan kembali.
        echo.
        pause
        exit /b 1
    )
    echo.
    echo [OK] Semua dependensi berhasil diinstal!
    echo.
) else (
    echo [OK] Seluruh dependensi node_modules lengkap.
    echo.
)

:: 5. Jalankan server dan buka browser kontrol secara otomatis
echo ========================================================
echo   MENJALANKAN SERVER OVERLAY DI PORT 4000...
echo ========================================================
echo.
echo URL yang tersedia:
echo   - Control Hub : http://localhost:4000/control.html
echo   - Overlay BP  : http://localhost:4000/bp1.html
echo   - Scoreboard  : http://localhost:4000/sb1.html
echo.
echo (Tekan Ctrl + C untuk mematikan server)
echo.

:: Membuka halaman control.html di browser default setelah jeda 1 detik
start "" http://localhost:4000/control.html

:: Jalankan Node.js server
node server.js

if %errorlevel% neq 0 (
    echo.
    echo [PERINGATAN] Server berhenti dengan kode keluar: %errorlevel%
    pause
)

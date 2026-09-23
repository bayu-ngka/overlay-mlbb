import threading
import time
import os
import re
import json
import numpy as np
import cv2
import uvicorn
from fastapi import FastAPI, Response
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

import platform
from typing import Optional, Dict, Any, List

# Path ke file konfigurasi ROI
ROI_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "roi_config.json")

# Deteksi otomatis path Tesseract di Windows jika terinstall di lokasi standar
if platform.system() == "Windows":
    try:
        import ctypes
        # Set DPI Awareness agar koordinat window tidak meleset/zoom pada monitor scaling (125%, 150%)
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2) # Per-Monitor DPI Aware
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

    try:
        import pytesseract
        windows_tesseract_paths = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.expanduser(r"~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe")
        ]
        for tpath in windows_tesseract_paths:
            if os.path.exists(tpath):
                pytesseract.pytesseract.tesseract_cmd = tpath
                break
    except Exception:
        pass

def load_roi_config() -> Dict[str, Any]:
    """Membaca koordinat ROI dari file konfigurasi JSON."""
    if os.path.exists(ROI_CONFIG_PATH):
        try:
            with open(ROI_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[Warning] Gagal membaca {ROI_CONFIG_PATH}: {e}")
    # Fallback default konfigurasi jika file tidak ada
    return {
        "reference_resolution": {"width": 1920, "height": 1080},
        "pre_crop": {"titlebar_height": 28},
        "rois": {
            "center_header": {"y_start": 14, "y_end": 56, "x_start": 820, "x_end": 1080},
            "blue_gold": {"y_start": 14, "y_end": 56, "x_start": 730, "x_end": 845},
            "red_gold": {"y_start": 14, "y_end": 56, "x_start": 1060, "x_end": 1175}
        }
    }

# ==============================================================================
# OCR ENGINE HELPER (Apple Vision di macOS / Tesseract Fallback)
# ==============================================================================
def recognize_text_elements(cv_img: np.ndarray) -> List[Dict[str, Any]]:
    """
    Mengenali teks dan posisinya dalam potongan ROI gambar.
    Cross-platform:
    - macOS: Menggunakan Apple Vision Framework (bawaan macOS) untuk akselerasi hardware.
    - Windows & Linux: Menggunakan Tesseract OCR (pytesseract) dengan preprocessing kontras & scaling.
    """
    results = []

    # 1. Jalur macOS (Apple Vision Framework)
    if platform.system() == "Darwin":
        try:
            import Vision
            from Cocoa import NSData

            _, buf = cv2.imencode('.png', cv_img)
            nsdata = NSData.dataWithBytes_length_(buf.tobytes(), len(buf))
            req = Vision.VNRecognizeTextRequest.alloc().init()
            req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
            req.setUsesLanguageCorrection_(False)

            handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(nsdata, None)
            handler.performRequests_error_([req], None)

            w, h = cv_img.shape[1], cv_img.shape[0]
            for obs in req.results() or []:
                cand = obs.topCandidates_(1)
                if cand:
                    bx = obs.boundingBox()
                    px_x = int(bx.origin.x * w)
                    results.append({
                        "text": cand[0].string().strip(),
                        "x": px_x
                    })
            if results:
                return results
        except Exception:
            pass

    # 2. Jalur Universal (Windows, Linux, atau fallback macOS tanpa Vision)
    try:
        import pytesseract
        gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
        up = cv2.resize(gray, (0, 0), fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        norm = cv2.normalize(up, None, 0, 255, cv2.NORM_MINMAX)

        # Coba beberapa mode PSM (PSM 7: single line, PSM 6: uniform block)
        txt = pytesseract.image_to_string(norm, config='--oem 3 --psm 7').strip()
        if not txt:
            txt = pytesseract.image_to_string(norm, config='--oem 3 --psm 6').strip()

        if txt:
            # Normalisasi jika Tesseract membaca "111k" tanpa titik
            m_k = re.search(r'([0-9]{3,})k', txt, re.IGNORECASE)
            if m_k:
                num_p = m_k.group(1)
                fixed_k = num_p[:-1] + "." + num_p[-1] + "k"
                txt = txt.replace(m_k.group(0), fixed_k)

            results.append({"text": txt, "x": 0})
    except Exception:
        pass

    return results

def parse_gold_display(text: str, default: str = "0") -> str:
    """
    Mengambil format tampilan teks gold asli dari layar MLBB.
    Jika di bawah 10k: '1500', jika di atas 9999: '11.1k' atau '11,1k'.
    """
    text = text.strip()
    text = text.replace("$", "").strip()
    match = re.search(r"[0-9]+(?:[\.,][0-9]+)?\s*k?", text, re.IGNORECASE)
    if match:
        return match.group(0).replace(" ", "")
    return default

def gold_to_int(val: Any) -> int:
    """Mengonversi nilai gold (string '11.1k' atau integer) ke angka integer untuk kalkulasi selisih."""
    if isinstance(val, (int, float)):
        return int(val)
    val_str = str(val).strip().lower().replace(",", ".")
    if "k" in val_str:
        num_part = re.sub(r"[^0-9\.]", "", val_str)
        try:
            return int(float(num_part) * 1000)
        except ValueError:
            return 0
    num_part = re.sub(r"[^0-9]", "", val_str)
    return int(num_part) if num_part else 0

def read_single_digit(crop: np.ndarray) -> int:
    """Membaca digit tunggal (misal turret, turtle, kills) dengan preprocessing khusus."""
    try:
        import pytesseract
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        norm = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
        _, th = cv2.threshold(norm, 80, 255, cv2.THRESH_BINARY)
        inv = cv2.bitwise_not(th)
        up = cv2.resize(inv, (0, 0), fx=3, fy=3, interpolation=cv2.INTER_NEAREST)
        padded = cv2.copyMakeBorder(up, 25, 25, 25, 25, cv2.BORDER_CONSTANT, value=255)
        txt = pytesseract.image_to_string(padded, config='--oem 3 --psm 10 -c tessedit_char_whitelist=0123456789').strip()
        if txt.isdigit():
            return int(txt)
    except Exception:
        pass
    return 0

def parse_kda_string(raw_text: str) -> Optional[str]:
    """
    Parser cerdas untuk mengurai format KDA (K/D/A) dan menangani kasus jika slash '/'
    terbaca sebagai '|', 'I', 'l', '\\', atau angka '1'.
    """
    if not raw_text:
        return None
    # 1. Bersihkan spasi dan simbol pemisah yang mirip garis miring
    cleaned = raw_text.strip().replace(" ", "").replace("|", "/").replace("\\", "/").replace("I", "/").replace("l", "/")

    # 2. Cek apakah sudah membentuk pola K/D/A yang benar
    match = re.search(r"(\d+)/(\d+)/(\d+)", cleaned)
    if match:
        k, d, a = match.groups()
        return f"{int(k)}/{int(d)}/{int(a)}"

    # 3. Jika hanya ada 1 slash (misal "8/12" atau "81/2" di mana salah satu slash terbaca 1)
    match_half = re.search(r"(\d+)/(\d+)", cleaned)
    if match_half:
        p1, p2 = match_half.groups()
        if len(p2) >= 2 and p2[0] == "1":
            # Kasus "8/12" -> K=8, D=1, A=2
            return f"{int(p1)}/1/{int(p2[1:])}"
        elif len(p1) >= 2 and p1[-1] == "1":
            # Kasus "81/2" -> K=8, D=1, A=2
            return f"{int(p1[:-1])}/1/{int(p2)}"

    # 4. Fallback jika semua slash terbaca menjadi angka 1 (misal "81112" -> 8/1/2)
    digits_only = re.sub(r"[^0-9]", "", cleaned)
    if len(digits_only) == 4 and digits_only[1] == "1" and digits_only[2] == "1":
        # Pola: K 1 D A -> misal 8 1 1 2 -> 8/1/2
        return f"{digits_only[0]}/{digits_only[2]}/{digits_only[3]}"
    elif len(digits_only) == 3:
        # Pola minimal: 3 digit misal 812 di mana 1 adalah D
        return f"{digits_only[0]}/{digits_only[1]}/{digits_only[2]}"

    return cleaned if "/" in cleaned else None

def read_kda_text(crop: np.ndarray) -> Optional[str]:
    """Membaca teks KDA dengan pembesaran khusus dan pembersihan kontras."""
    try:
        # Resize 3x agar garis miring dan angka kecil lebih jelas
        up = cv2.resize(crop, (0, 0), fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        res = recognize_text_elements(up)
        if res:
            raw_text = res[0].get("text", "")
            parsed = parse_kda_string(raw_text)
            if parsed:
                return parsed
            return raw_text
    except Exception as e:
        print(f"[KDA OCR Error] {e}")
    return None

def extract_digits(text: str, default: int = 0) -> int:
    """Mengambil angka integer dari string hasil OCR, menangani huruf yang mirip angka."""
    if not text:
        return default
    # Perbaiki huruf yang sering tertukar dengan angka (misal 'g' atau 'q' terbaca sebagai 9, 'O'/'o' sebagai 0)
    cleaned = text.strip()
    cleaned = re.sub(r'[gGq]', '9', cleaned)
    cleaned = re.sub(r'[oOD]', '0', cleaned)
    cleaned = re.sub(r'[lI|]', '1', cleaned)
    cleaned = re.sub(r'[sS]', '5', cleaned)
    cleaned = re.sub(r'[b]', '6', cleaned)
    clean = re.sub(r'[^0-9]', '', cleaned)
    return int(clean) if clean else default

# Inisialisasi FastAPI
app = FastAPI(title="MLBB OCR Data Provider")

# ==============================================================================
# WINDOW CAPTURE HELPERS (macOS & Cross-platform)
# ==============================================================================
def get_available_windows() -> List[Dict[str, Any]]:
    """
    Mengambil daftar jendela yang sedang aktif/terbuka.
    Pada macOS menggunakan CoreGraphics / Quartz.
    """
    windows = []
    system = platform.system()

    if system == "Darwin":
        try:
            import Quartz
            # Gunakan kCGWindowListOptionAll agar jendela di background / Space lain (seperti scrcpy) tetap terbaca
            options = Quartz.kCGWindowListOptionAll
            raw_list = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID)

            IGNORE_APPS = {
                'Window Server', 'Dock', 'SystemUIServer', 'Control Center', 
                'Notification Center', 'Spotlight', 'Wallpaper', 'AutoFill',
                'loginwindow', 'Creative Cloud'
            }

            for w in raw_list:
                layer = w.get("kCGWindowLayer", 0)
                bounds = w.get("kCGWindowBounds", {})
                width = bounds.get("Width", 0)
                height = bounds.get("Height", 0)
                owner = w.get("kCGWindowOwnerName", "").strip()
                name = w.get("kCGWindowName", "").strip()
                wid = w.get("kCGWindowNumber", 0)
                alpha = w.get("kCGWindowAlpha", 1.0)

                if owner in IGNORE_APPS:
                    continue

                # Filter jendela normal (layer 0, ukuran masuk akal, bukan window dummy kosong)
                if layer == 0 and width >= 150 and height >= 150 and alpha > 0:
                    if not name and width == 500 and height == 500:
                        continue
                    
                    title = f"[{owner}] {name}" if name else f"[{owner}]"
                    windows.append({
                        "id": wid,
                        "title": title,
                        "owner": owner,
                        "name": name,
                        "width": int(width),
                        "height": int(height),
                        "bounds": bounds
                    })
        except Exception as e:
            print(f"[Warning] Gagal mengambil window list via Quartz: {e}")
    elif system == "Windows":
        # Jalur Windows Native (win32gui): Menjamin HWND window valid dan akurat
        try:
            import win32gui
            def win_enum_callback(hwnd, extra):
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd).strip()
                    cl_left, cl_top, cl_right, cl_bottom = win32gui.GetClientRect(hwnd)
                    width = cl_right - cl_left
                    height = cl_bottom - cl_top
                    # Filter jendela normal (bukan toolbar atau invisible tool window)
                    if title and width >= 150 and height >= 150:
                        extra.append({
                            "id": hwnd,
                            "hwnd": hwnd,
                            "title": title,
                            "owner": "Windows",
                            "name": title,
                            "width": width,
                            "height": height
                        })
            win32gui.EnumWindows(win_enum_callback, windows)
        except Exception as e:
            print(f"[Warning] Gagal enum windows via win32gui: {e}")
    else:
        # Jalur Linux / Generic
        try:
            import pygetwindow as gw
            all_windows = gw.getAllWindows()
            for i, w in enumerate(all_windows):
                title = (w.title or "").strip()
                if title and w.width >= 150 and w.height >= 150:
                    windows.append({
                        "id": getattr(w, "_hWnd", i),
                        "title": title,
                        "owner": "App",
                        "name": title,
                        "width": int(w.width),
                        "height": int(w.height),
                        "window_obj": w
                    })
        except Exception:
            pass

    return windows


def get_available_cameras() -> List[Dict[str, Any]]:
    """
    Mendeteksi daftar perangkat video capture yang tersedia,
    termasuk Hardware Capture Card (USB HDMI), Webcam fisik, dan
    Virtual Camera (seperti OBS Virtual Camera, vMix Video, Cam Link, dll).
    """
    cameras = []
    system = platform.system()
    cam_names = []

    # 1. Ambil nama deskriptif perangkat jika memungkinkan
    if system == "Darwin":
        try:
            import subprocess
            out = subprocess.check_output(['system_profiler', 'SPCameraDataType'], text=True, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                line_str = line.strip()
                if line.startswith('    ') and not line.startswith('      ') and line_str.endswith(':'):
                    c_name = line_str[:-1].strip()
                    if c_name and c_name != 'Camera':
                        cam_names.append(c_name)
        except Exception:
            pass
    elif system == "Windows":
        try:
            import subprocess
            # Query PnP Entity untuk nama kamera / virtual video driver
            ps_cmd = 'Get-CimInstance Win32_PnPEntity | Where-Object { $_.PNPClass -eq "Camera" -or $_.PNPClass -eq "Image" } | Select-Object -ExpandProperty Name'
            out = subprocess.check_output(['powershell', '-NoProfile', '-Command', ps_cmd], text=True, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                name = line.strip()
                if name:
                    cam_names.append(name)
        except Exception:
            pass

    # 2. Cek ketersediaan indeks VideoCapture (0 sampai 7)
    for idx in range(8):
        try:
            cap = cv2.VideoCapture(idx)
            if cap.isOpened():
                # Dapatkan nama dari deteksi sistem jika ada
                if idx < len(cam_names):
                    device_name = cam_names[idx]
                else:
                    device_name = f"Video / Virtual Camera #{idx}"

                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                cameras.append({
                    "index": idx,
                    "name": device_name,
                    "width": w,
                    "height": h
                })
                cap.release()
        except Exception:
            pass

    return cameras


def capture_window_frame(window_info: Dict[str, Any]) -> Optional[np.ndarray]:
    """
    Mengambil screenshot/frame dari window tertentu dan mengembalikan format OpenCV BGR.
    Cross-platform:
    - macOS: CGWindowListCreateImage
    - Windows / Linux: mss bounding box / win32 PrintWindow
    """
    system = platform.system()
    if system == "Darwin":
        try:
            import Quartz
            wid = window_info["id"]
            image_ref = Quartz.CGWindowListCreateImage(
                Quartz.CGRectNull,
                Quartz.kCGWindowListOptionIncludingWindow,
                wid,
                Quartz.kCGWindowImageBoundsIgnoreFraming | Quartz.kCGWindowImageNominalResolution
            )
            if not image_ref:
                return None
            width = Quartz.CGImageGetWidth(image_ref)
            height = Quartz.CGImageGetHeight(image_ref)
            bytes_per_row = Quartz.CGImageGetBytesPerRow(image_ref)
            prov = Quartz.CGImageGetDataProvider(image_ref)
            data = Quartz.CGDataProviderCopyData(prov)

            arr = np.frombuffer(data, dtype=np.uint8).reshape((height, bytes_per_row))
            arr = arr[:, :width * 4].reshape((height, width, 4))
            bgr = cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)
            return bgr
        except Exception:
            return None
    elif system == "Windows":
        # Jalur Windows Murni Window Capture (Bukan Screen Capture)
        hwnd = window_info.get("hwnd") or window_info.get("id")
        if hwnd and isinstance(hwnd, int):
            # 1. Metode PrintWindow dengan PW_RENDERFULLCONTENT (Capture langsung dari GPU/Window buffer scrcpy)
            try:
                import win32gui
                import win32ui

                # Dapatkan ukuran client window (konten game saja tanpa titlebar)
                cl_left, cl_top, cl_right, cl_bottom = win32gui.GetClientRect(hwnd)
                w_w = cl_right - cl_left
                w_h = cl_bottom - cl_top

                if w_w > 50 and w_h > 50:
                    hwndDC = win32gui.GetDC(hwnd)
                    mfcDC = win32ui.CreateDCFromHandle(hwndDC)
                    saveDC = mfcDC.CreateCompatibleDC()

                    saveBitMap = win32ui.CreateBitmap()
                    saveBitMap.CreateCompatibleBitmap(mfcDC, w_w, w_h)
                    saveDC.SelectObject(saveBitMap)

                    # PW_RENDERFULLCONTENT = 2 (Menangkap buffer DirectX/OpenGL scrcpy secara langsung)
                    result = ctypes.windll.user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), 2)
                    if result == 0:
                        # Fallback flag 1 (PW_CLIENTONLY)
                        result = ctypes.windll.user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), 1)
                    if result == 0:
                        # Fallback flag 0 (Default)
                        result = ctypes.windll.user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), 0)

                    if result == 1:
                        bmpinfo = saveBitMap.GetInfo()
                        bmpstr = saveBitMap.GetBitmapBits(True)
                        img = np.frombuffer(bmpstr, dtype=np.uint8).reshape((bmpinfo['bmHeight'], bmpinfo['bmWidth'], 4))
                        win32gui.DeleteObject(saveBitMap.GetHandle())
                        saveDC.DeleteDC()
                        mfcDC.DeleteDC()
                        win32gui.ReleaseDC(hwnd, hwndDC)
                        # Konversi dari BGRA ke BGR
                        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

                    win32gui.DeleteObject(saveBitMap.GetHandle())
                    saveDC.DeleteDC()
                    mfcDC.DeleteDC()
                    win32gui.ReleaseDC(hwnd, hwndDC)
            except Exception:
                pass

            # 2. Fallback DWM Desktop Cropping HANYA jika PrintWindow tidak didukung driver
            try:
                import mss
                import win32gui
                # Titik (0, 0) Client Area diubah ke koordinat layar fisik
                pt = win32gui.ClientToScreen(hwnd, (0, 0))
                cl_left, cl_top, cl_right, cl_bottom = win32gui.GetClientRect(hwnd)
                w_w = cl_right - cl_left
                w_h = cl_bottom - cl_top
                if w_w > 50 and w_h > 50:
                    with mss.mss() as sct:
                        # Dapatkan monitor tempat window berada
                        bbox = {"left": int(pt[0]), "top": int(pt[1]), "width": int(w_w), "height": int(w_h)}
                        img = np.array(sct.grab(bbox))
                        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
            except Exception:
                pass

    # Fallback Linux / generic menggunakan mss dan window_obj
    try:
        import mss
        w_obj = window_info.get("window_obj")
        if w_obj:
            bbox = {"top": int(w_obj.top), "left": int(w_obj.left), "width": int(w_obj.width), "height": int(w_obj.height)}
            with mss.mss() as sct:
                img = np.array(sct.grab(bbox))
                return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    except Exception:
        pass

    return None

# Mengizinkan CORS agar bisa diakses oleh browser overlay (OBS / Web)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==============================================================================
# GLOBAL DATA STORE
# Menyimpan hasil bacaan OCR terkini yang akan di-serve ke endpoint API
# ==============================================================================
ocr_data_store = {
    "status": "initializing",
    "last_updated": None,
    "game_timer": "00:00",
    "score": {
        "blue_kills": 0,
        "red_kills": 0
    },
    "gold": {
        "blue_total": "0",
        "red_total": "0",
        "difference": 0,
        "difference_formatted": "0"
    },
    "objectives": {
        "blue_turrets": 0,
        "red_turrets": 0,
        "blue_turtles": 0,
        "red_turtles": 0,
        "blue_lords": 0,
        "red_lords": 0
    },
    "players": {
        "blue_team": [],
        "red_team": []
    }
}

# Lock untuk keamanan akses variabel global antar thread
data_lock = threading.Lock()
frame_lock = threading.Lock()
latest_annotated_frame: Optional[bytes] = None
is_running = True


# ==============================================================================
# WORKER: CAPTURE & OCR PROCESSING LOOP
# ==============================================================================
def background_worker(capture_mode: int, selected_window: Optional[Dict[str, Any]] = None, camera_device: Optional[Dict[str, Any]] = None):
    global ocr_data_store, is_running, latest_annotated_frame
    print(f"\n[Worker] Memulai Background Worker pada mode: {capture_mode}...")

    # 1. Inisialisasi Sumber Capture
    cap = None

    if capture_mode == 1:
        # Mode 1: Window Capture
        if selected_window:
            print(f"[Worker] Window Capture aktif pada target: {selected_window['title']} (Ukuran: {selected_window['width']}x{selected_window['height']})")
        else:
            print("[Worker Error] Target window belum dipilih!")
            return
    elif capture_mode == 2:
        # Mode 2: Video Capture Device (HDMI Capture Card / Webcam / OBS Virtual Camera / vMix)
        device_index = camera_device.get("index", 0) if camera_device else 0
        device_name = camera_device.get("name", f"Camera #{device_index}") if camera_device else f"Camera #{device_index}"
        
        cap = cv2.VideoCapture(device_index)
        if not cap.isOpened():
            print(f"[Worker Error] Gagal membuka video capture device '{device_name}' (Index: {device_index})")
            return
            
        # Atur resolusi capture ke 1080p (jika didukung perangkat)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f"[Worker] Video Device Aktif: {device_name} (Index: {device_index}, Resolusi: {actual_w}x{actual_h})")

    # ==========================================================================
    # Loop Pengambilan Frame & Ekstraksi OCR
    # ==========================================================================
    while is_running:
        frame = None

        # A. Ambil Frame berdasarkan mode pilihan
        if capture_mode == 1 and selected_window:
            frame = capture_window_frame(selected_window)
            if frame is None:
                # Jendela mungkin diminimize, tertutup, atau tidak dapat di-render
                print(f"[Worker] Menunggu frame dari window '{selected_window.get('title', 'Unknown')}'...", end="\r")
                time.sleep(0.3)
                continue
        elif capture_mode == 2 and cap:
            ret, frame = cap.read()
            if not ret or frame is None:
                print("[Worker] Menunggu video frame dari HDMI Capture...", end="\r")
                time.sleep(0.2)
                continue

        if frame is not None:
            # Dapatkan dimensi frame yang ditangkap
            h, w = frame.shape[:2]

            # ------------------------------------------------------------------
            # PROSES CROP, PREPROCESSING & OCR RIIL BERDASARKAN ROI CONFIG
            # ------------------------------------------------------------------
            try:
                roi_cfg = load_roi_config()
                pre_crop = roi_cfg.get("pre_crop", {})
                titlebar_h = pre_crop.get("titlebar_height", 0)

                # Pemotongan title bar scrcpy otomatis per platform (hanya berlaku jika mode Window Capture)
                if capture_mode == 1:
                    if platform.system() == "Darwin":
                        t_crop = pre_crop.get("titlebar_height_macos", pre_crop.get("titlebar_height", 28))
                    elif platform.system() == "Windows":
                        t_crop = pre_crop.get("titlebar_height_windows", 32)
                    else:
                        t_crop = 0
                else:
                    # Video capture card / Virtual Camera (OBS/vMix) sudah full frame murni tanpa titlebar OS
                    t_crop = 0

                if t_crop > 0 and h > t_crop + 100:
                    game_content = frame[t_crop:, :]
                else:
                    game_content = frame
                gh, gw = game_content.shape[:2]

                # Skala adaptif berbasis tinggi game (default 1080p)
                base_h = roi_cfg.get("reference_resolution", {}).get("base_height", 1080)
                scale = gh / float(base_h) if base_h > 0 else 1.0
                center_x = gw // 2

                rois = roi_cfg.get("rois", {})

                # Helper menghitung koordinat pixel absolut aktual dari konfigurasi ROI
                def get_roi_rect(roi_key: str, r_def: Dict[str, Any]) -> tuple:
                    anchor = r_def.get("anchor", "center_top")
                    rw = int(round(r_def.get("width", 50) * scale))
                    rh = int(round(r_def.get("height", 40) * scale))

                    # 1. Hitung X
                    if "offset_x" in r_def:
                        # Relatif terhadap titik tengah horizontal (center_x)
                        rx = int(round(center_x + (r_def["offset_x"] * scale) - (rw / 2.0)))
                    else:
                        # Fallback koordinat statis x
                        rx = int(round(r_def.get("x", 0) * scale))

                    # 2. Hitung Y
                    if anchor == "center_bottom":
                        if "offset_y" in r_def:
                            ry = int(round(gh + (r_def["offset_y"] * scale)))
                        else:
                            ry = int(round(r_def.get("y", 0) * scale))
                    else:
                        ry = int(round(r_def.get("y", 14) * scale))

                    # Boundary checking agar tidak keluar dari frame
                    rx = max(0, min(rx, gw - rw))
                    ry = max(0, min(ry, gh - rh))
                    rw = max(1, min(rw, gw - rx))
                    rh = max(1, min(rh, gh - ry))
                    return rx, ry, rw, rh

                # Helper crop aman dari game_content asli tanpa distorsi stretch
                def crop_box(key: str) -> Optional[np.ndarray]:
                    if key in rois:
                        rx, ry, rw, rh = get_roi_rect(key, rois[key])
                        if rw > 0 and rh > 0:
                            return game_content[ry:ry+rh, rx:rx+rw]
                    return None

                # 1. BACA GAME TIMER
                timer_str = "00:00"
                c_timer = crop_box("game_timer")
                if c_timer is not None:
                    up_t = cv2.resize(c_timer, (0, 0), fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
                    res_t = recognize_text_elements(up_t)
                    if res_t:
                        t_candidate = res_t[0].get("text", "")
                        if ":" in t_candidate or (len(t_candidate) >= 4 and t_candidate.replace(":", "").isdigit()):
                            timer_str = t_candidate

                # 2. BACA BLUE & RED GOLD (Mempertahankan format k jika di atas 9999, misal 11.1k)
                b_gold_str = ""
                c_bg = crop_box("blue_gold")
                if c_bg is not None:
                    up_bg = cv2.resize(c_bg, (0, 0), fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
                    res_bg = recognize_text_elements(up_bg)
                    if res_bg:
                        b_gold_str = parse_gold_display(res_bg[0].get("text", ""), "")

                r_gold_str = ""
                c_rg = crop_box("red_gold")
                if c_rg is not None:
                    up_rg = cv2.resize(c_rg, (0, 0), fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
                    res_rg = recognize_text_elements(up_rg)
                    if res_rg:
                        r_gold_str = parse_gold_display(res_rg[0].get("text", ""), "")

                # 3. BACA KILLS (Blue & Red - Mendukung 1 digit dan 2 digit angka kill)
                b_kills = 0
                c_bk = crop_box("blue_kills")
                if c_bk is not None:
                    # Simpan snapshot crop untuk diagnosa jika masih 0
                    cv2.imwrite("debug_blue_kills.png", c_bk)
                    
                    # Prioritas 1: Tesseract dengan whitelist angka 0-9 dan PSM 7 (Sangat akurat untuk angka font MLBB)
                    try:
                        import pytesseract
                        gray = cv2.cvtColor(c_bk, cv2.COLOR_BGR2GRAY)
                        norm = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
                        up_t = cv2.resize(norm, (0, 0), fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
                        t_txt = pytesseract.image_to_string(up_t, config='--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789').strip()
                        if t_txt and t_txt.isdigit():
                            b_kills = int(t_txt)
                    except Exception:
                        pass

                    # Prioritas 2: Apple Vision / Standard recognizer jika Tesseract belum dapat
                    if b_kills == 0:
                        up_bk = cv2.resize(c_bk, (0, 0), fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
                        res_bk = recognize_text_elements(up_bk)
                        if res_bk:
                            b_kills = extract_digits(res_bk[0].get("text", ""), 0)

                r_kills = 0
                c_rk = crop_box("red_kills")
                if c_rk is not None:
                    try:
                        import pytesseract
                        gray_r = cv2.cvtColor(c_rk, cv2.COLOR_BGR2GRAY)
                        norm_r = cv2.normalize(gray_r, None, 0, 255, cv2.NORM_MINMAX)
                        up_tr = cv2.resize(norm_r, (0, 0), fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
                        t_txt_r = pytesseract.image_to_string(up_tr, config='--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789').strip()
                        if t_txt_r and t_txt_r.isdigit():
                            r_kills = int(t_txt_r)
                    except Exception:
                        pass

                    if r_kills == 0:
                        up_rk = cv2.resize(c_rk, (0, 0), fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
                        res_rk = recognize_text_elements(up_rk)
                        if res_rk:
                            r_kills = extract_digits(res_rk[0].get("text", ""), 0)

                # 4. BACA OBJECTIVES (Turrets & Turtles)
                b_turrets = 0
                c_btur = crop_box("blue_turrets")
                if c_btur is not None:
                    b_turrets = read_single_digit(c_btur)

                b_turtles = 0
                c_bturt = crop_box("blue_turtles")
                if c_bturt is not None:
                    b_turtles = read_single_digit(c_bturt)

                r_turtles = 0
                c_rturt = crop_box("red_turtles")
                if c_rturt is not None:
                    r_turtles = read_single_digit(c_rturt)

                r_turrets = 0
                c_rtur = crop_box("red_turrets")
                if c_rtur is not None:
                    r_turrets = read_single_digit(c_rtur)

                # 4b. BACA ROI KHUSUS (Termasuk KDA atau ROI bertipe custom lainnya)
                custom_roi_data = {}
                for r_name, r_conf in rois.items():
                    r_type = r_conf.get("type", "")
                    if r_type == "kda" or "kda" in r_name:
                        c_kda = crop_box(r_name)
                        if c_kda is not None:
                            val_kda = read_kda_text(c_kda)
                            if val_kda:
                                custom_roi_data[r_name] = val_kda

                # 5. UPDATE HASIL KE GLOBAL DATA STORE
                with data_lock:
                    current_time_str = time.strftime("%H:%M:%S")
                    ocr_data_store["status"] = "running"
                    ocr_data_store["last_updated"] = current_time_str
                    if timer_str and timer_str != "00:00":
                        ocr_data_store["game_timer"] = timer_str
                    ocr_data_store["score"]["blue_kills"] = b_kills
                    ocr_data_store["score"]["red_kills"] = r_kills

                    if b_gold_str:
                        ocr_data_store["gold"]["blue_total"] = b_gold_str
                    if r_gold_str:
                        ocr_data_store["gold"]["red_total"] = r_gold_str

                    # Hitung selisih numerik (difference)
                    b_int = gold_to_int(ocr_data_store["gold"]["blue_total"])
                    r_int = gold_to_int(ocr_data_store["gold"]["red_total"])
                    diff_val = b_int - r_int
                    ocr_data_store["gold"]["difference"] = diff_val

                    # Format selisih jika ingin format k juga
                    if abs(diff_val) >= 1000:
                        ocr_data_store["gold"]["difference_formatted"] = f"{diff_val / 1000:.1f}k"
                    else:
                        ocr_data_store["gold"]["difference_formatted"] = str(diff_val)

                    ocr_data_store["objectives"]["blue_turrets"] = b_turrets
                    ocr_data_store["objectives"]["red_turrets"] = r_turrets
                    ocr_data_store["objectives"]["blue_turtles"] = b_turtles
                    ocr_data_store["objectives"]["red_turtles"] = r_turtles

                    # Simpan data kda / custom rois
                    if "kda" not in ocr_data_store:
                        ocr_data_store["kda"] = {}
                    for k_name, k_val in custom_roi_data.items():
                        ocr_data_store["kda"][k_name] = k_val

                # 6. RENDER VISUAL PREVIEW ROI (Untuk verifikasi posisi ROI di browser)
                try:
                    annotated = game_content.copy()
                    for roi_key, roi_val in rois.items():
                        rx, ry, rw, rh = get_roi_rect(roi_key, roi_val)
                        if rw > 0 and rh > 0:
                            # Warna kotak disesuaikan dengan tipe tim
                            color = (0, 255, 255) # Default kuning
                            if "blue" in roi_key:
                                color = (255, 200, 0) # Cyan/Biru muda di BGR
                            elif "red" in roi_key:
                                color = (50, 50, 255) # Merah di BGR
                            elif "timer" in roi_key:
                                color = (0, 255, 0)   # Hijau

                            # Gambar bounding box kotak saja (bersih tanpa tulisan teks yang menumpuk)
                            cv2.rectangle(annotated, (rx, ry), (rx + rw, ry + rh), color, 2)

                    _, encoded_jpeg = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    with frame_lock:
                        latest_annotated_frame = encoded_jpeg.tobytes()
                except Exception as e_prev:
                    print(f"[Preview Render Error] {e_prev}")

            except Exception as e:
                print(f"[Worker OCR Error] {e}")

        # Kontrol jeda loop OCR (0.4 detik sekali)
        time.sleep(0.4)

    # Cleanup resources saat loop selesai
    if cap:
        cap.release()
    print("[Worker] Background Worker dihentikan.")


# ==============================================================================
# HTTP API SERVER (FastAPI Endpoints)
# ==============================================================================
@app.get("/")
def index():
    return {
        "message": "MLBB OCR Service is running",
        "api_data": "/api/mlbb-data",
        "roi_checker": "/roi-checker",
        "live_stream": "/preview/stream"
    }

@app.get("/api/mlbb-data")
def get_mlbb_data():
    """
    Mengembalikan data OCR terkini dari Background Worker dalam format JSON
    """
    with data_lock:
        return ocr_data_store

@app.get("/preview/frame.jpg")
def get_preview_frame():
    """
    Mengembalikan 1 snapshot JPEG dari frame dengan visualisasi kotak ROI
    """
    with frame_lock:
        if latest_annotated_frame is None:
            return Response(content=b"", status_code=503)
        return Response(content=latest_annotated_frame, media_type="image/jpeg")

def generate_mjpeg_stream():
    """Generator untuk live MJPEG stream"""
    while is_running:
        with frame_lock:
            frame_data = latest_annotated_frame
        if frame_data is not None:
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" + frame_data + b"\r\n")
        time.sleep(0.1)

@app.get("/preview/stream")
def get_preview_stream():
    """
    Live Video Stream MJPEG yang bisa dibuka langsung di browser atau OBS Browser Source
    """
    return StreamingResponse(
        generate_mjpeg_stream(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

@app.get("/roi-checker", response_class=HTMLResponse)
def roi_checker_ui():
    """
    Halaman web interaktif untuk memonitor kotak ROI secara realtime
    """
    html_content = """
    <!DOCTYPE html>
    <html lang="id">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>MLBB OCR - Live ROI Checker</title>
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700&display=swap" rel="stylesheet">
        <style>
            * { box-sizing: border-box; margin: 0; padding: 0; }
            body {
                background: #0f172a;
                color: #f8fafc;
                font-family: 'Plus Jakarta Sans', sans-serif;
                display: flex;
                flex-direction: column;
                align-items: center;
                min-height: 100vh;
                padding: 24px;
            }
            .header {
                max-width: 1200px;
                width: 100%;
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 20px;
            }
            .title {
                font-size: 22px;
                font-weight: 700;
                display: flex;
                align-items: center;
                gap: 10px;
            }
            .badge {
                background: #22c55e;
                color: #0f172a;
                font-size: 11px;
                font-weight: 700;
                padding: 4px 8px;
                border-radius: 6px;
                text-transform: uppercase;
            }
            .card {
                background: #1e293b;
                border-radius: 14px;
                border: 1px solid #334155;
                padding: 16px;
                max-width: 1200px;
                width: 100%;
                box-shadow: 0 10px 30px rgba(0,0,0,0.5);
            }
            .stream-container {
                position: relative;
                width: 100%;
                border-radius: 10px;
                overflow: hidden;
                background: #000;
                aspect-ratio: 16 / 9;
                display: flex;
                align-items: center;
                justify-content: center;
            }
            .stream-container img {
                width: 100%;
                height: 100%;
                object-fit: contain;
                display: block;
            }
            .legend-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 12px;
                margin-top: 20px;
            }
            .legend-item {
                display: flex;
                align-items: center;
                gap: 10px;
                font-size: 13px;
                background: #0f172a;
                padding: 10px 14px;
                border-radius: 8px;
                border: 1px solid #334155;
            }
            .dot {
                width: 12px;
                height: 12px;
                border-radius: 3px;
                flex-shrink: 0;
            }
            .dot-blue { background: #38bdf8; }
            .dot-red { background: #f87171; }
            .dot-timer { background: #4ade80; }
            .dot-yellow { background: #facc15; }
            .info-panel {
                margin-top: 16px;
                padding: 14px;
                background: #0f172a;
                border-radius: 8px;
                border-left: 4px solid #38bdf8;
                font-size: 13px;
                color: #94a3b8;
                line-height: 1.6;
            }
            code {
                background: #1e293b;
                color: #e2e8f0;
                padding: 2px 6px;
                border-radius: 4px;
                font-family: monospace;
            }
        </style>
    </head>
    <body>
        <div class="header">
            <div class="title">
                <span>🎯 Live ROI Position Checker</span>
                <span class="badge">Live 1080p</span>
            </div>
            <div>
                <a href="/api/mlbb-data" target="_blank" style="color: #38bdf8; text-decoration: none; font-size: 13px; font-weight: 600;">Lihat Data JSON ↗</a>
            </div>
        </div>

        <div class="card">
            <div class="stream-container">
                <div id="loadingText" style="position: absolute; color: #94a3b8; font-size: 14px;">Menunggu frame dari worker OCR...</div>
                <img id="roiPreview" src="/preview/frame.jpg" alt="Live ROI Stream" style="z-index: 1;">
            </div>

            <!-- LIVE DATA OCR STATS & JSON (Tepat di bawah gambar, di atas keterangan panduan) -->
            <div style="margin-top: 20px; padding: 16px; background: #0f172a; border-radius: 10px; border: 1px solid #334155;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                    <div style="font-weight: 700; font-size: 15px; display: flex; align-items: center; gap: 8px;">
                        <span>📊 Data Hasil Bacaan OCR Real-Time</span>
                        <span id="dataStatus" style="background: #334155; font-size: 11px; padding: 2px 8px; border-radius: 4px; color: #94a3b8;">Syncing...</span>
                    </div>
                    <div style="font-size: 12px; color: #64748b;">Update: <span id="lastUpdated">-</span></div>
                </div>

                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; margin-bottom: 14px;">
                    <div style="background: #1e293b; padding: 10px; border-radius: 8px; text-align: center; border: 1px solid #334155;">
                        <div style="font-size: 11px; color: #94a3b8; text-transform: uppercase;">Timer</div>
                        <div id="statTimer" style="font-size: 18px; font-weight: 700; color: #4ade80;">00:00</div>
                    </div>
                    <div style="background: #1e293b; padding: 10px; border-radius: 8px; text-align: center; border: 1px solid #334155;">
                        <div style="font-size: 11px; color: #38bdf8; text-transform: uppercase;">Blue Kills</div>
                        <div id="statBlueKills" style="font-size: 18px; font-weight: 700; color: #38bdf8;">0</div>
                    </div>
                    <div style="background: #1e293b; padding: 10px; border-radius: 8px; text-align: center; border: 1px solid #334155;">
                        <div style="font-size: 11px; color: #f87171; text-transform: uppercase;">Red Kills</div>
                        <div id="statRedKills" style="font-size: 18px; font-weight: 700; color: #f87171;">0</div>
                    </div>
                    <div style="background: #1e293b; padding: 10px; border-radius: 8px; text-align: center; border: 1px solid #334155;">
                        <div style="font-size: 11px; color: #38bdf8; text-transform: uppercase;">Blue Gold</div>
                        <div id="statBlueGold" style="font-size: 18px; font-weight: 700; color: #38bdf8;">0</div>
                    </div>
                    <div style="background: #1e293b; padding: 10px; border-radius: 8px; text-align: center; border: 1px solid #334155;">
                        <div style="font-size: 11px; color: #f87171; text-transform: uppercase;">Red Gold</div>
                        <div id="statRedGold" style="font-size: 18px; font-weight: 700; color: #f87171;">0</div>
                    </div>
                    <div style="background: #1e293b; padding: 10px; border-radius: 8px; text-align: center; border: 1px solid #334155;">
                        <div style="font-size: 11px; color: #facc15; text-transform: uppercase;">KDA 1 (Biru)</div>
                        <div id="statKDA1" style="font-size: 18px; font-weight: 700; color: #facc15;">-</div>
                    </div>
                </div>

                <pre id="jsonViewer" style="background: #1e293b; color: #38bdf8; padding: 12px; border-radius: 8px; font-family: monospace; font-size: 12px; max-height: 220px; overflow-y: auto; border: 1px solid #334155;">Memuat data JSON...</pre>
            </div>

            <div class="legend-grid">
                <div class="legend-item">
                    <span class="dot dot-timer"></span>
                    <span><strong>Hijau:</strong> Game Timer</span>
                </div>
                <div class="legend-item">
                    <span class="dot dot-blue"></span>
                    <span><strong>Biru Muda:</strong> Tim Biru (Kills, Gold, Turret, Turtle, KDA)</span>
                </div>
                <div class="legend-item">
                    <span class="dot dot-red"></span>
                    <span><strong>Merah:</strong> Tim Merah (Kills, Gold, Turret, Turtle, KDA)</span>
                </div>
                <div class="legend-item">
                    <span class="dot dot-yellow"></span>
                    <span><strong>Kuning:</strong> Scoreboard / Object Lain</span>
                </div>
            </div>

            <div class="info-panel">
                💡 <strong>Cara Menyesuaikan Koordinat:</strong><br>
                Jika kotak ROI di atas belum pas di atas teks/angka game, Anda cukup mengedit file <code>roi_config.json</code> (ubah nilai <code>offset_x</code>, <code>y</code>, <code>width</code>, atau <code>height</code>). Skrip otomatis membaca koordinat baru setiap frame tanpa perlu restart aplikasi.
            </div>
        </div>

        <script>
            const img = document.getElementById('roiPreview');
            const loading = document.getElementById('loadingText');
            const jsonViewer = document.getElementById('jsonViewer');

            function refreshFrame() {
                const nextImg = new Image();
                nextImg.onload = function() {
                    img.src = this.src;
                    loading.style.display = 'none';
                    setTimeout(refreshFrame, 250);
                };
                nextImg.onerror = function() {
                    setTimeout(refreshFrame, 500);
                };
                nextImg.src = '/preview/frame.jpg?t=' + Date.now();
            }

            async function refreshJsonData() {
                try {
                    const res = await fetch('/api/mlbb-data');
                    if (res.ok) {
                        const data = await res.json();
                        jsonViewer.textContent = JSON.stringify(data, null, 2);
                        
                        document.getElementById('dataStatus').textContent = data.status || 'OK';
                        document.getElementById('dataStatus').style.background = '#22c55e22';
                        document.getElementById('dataStatus').style.color = '#4ade80';
                        document.getElementById('lastUpdated').textContent = data.last_updated || '-';
                        
                        document.getElementById('statTimer').textContent = data.game_timer || '00:00';
                        document.getElementById('statBlueKills').textContent = data.score?.blue_kills ?? 0;
                        document.getElementById('statRedKills').textContent = data.score?.red_kills ?? 0;
                        document.getElementById('statBlueGold').textContent = data.gold?.blue_total ?? '0';
                        document.getElementById('statRedGold').textContent = data.gold?.red_total ?? '0';
                        
                        if (data.kda && data.kda.blue_kda1) {
                            document.getElementById('statKDA1').textContent = data.kda.blue_kda1;
                        } else {
                            document.getElementById('statKDA1').textContent = '-';
                        }
                    }
                } catch (e) {
                    console.error("Gagal polling JSON", e);
                }
                setTimeout(refreshJsonData, 500);
            }

            img.onload = () => { loading.style.display = 'none'; };
            setTimeout(refreshFrame, 200);
            setTimeout(refreshJsonData, 300);
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


# ==============================================================================
# MAIN ENTRYPOINT DENGAN MENU CLI
# ==============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("    MLBB MULTI-ROI OCR & STREAM PROVIDER (PYTHON)")
    print("=" * 60)
    print("Pilih Sumber Video Capture:")
    print(" [1] Window Capture (Pilih jendela aplikasi tertentu)")
    print(" [2] Video / Virtual Camera (OBS Virtual Cam, vMix, USB HDMI Capture, Webcam)")
    print("=" * 60)

    # Input pilihan dari pengguna
    choice = input("Masukkan pilihan Anda (1 atau 2): ").strip()
    while choice not in ["1", "2"]:
        choice = input("Pilihan tidak valid. Masukkan 1 atau 2: ").strip()

    selected_mode = int(choice)
    target_window = None
    target_camera = None

    if selected_mode == 1:
        print("\nMemindai daftar jendela yang terbuka...")
        windows = get_available_windows()

        if not windows:
            print("[Warning] Tidak ditemukan jendela yang aktif. Pastikan jendela tidak terminimize.")
            exit(1)

        print("\nDaftar Window Tersedia:")
        print("-" * 60)
        for idx, win in enumerate(windows, start=1):
            dim_info = f"{win['width']}x{win['height']}"
            print(f" [{idx:2d}] {win['title']} ({dim_info})")
        print("-" * 60)

        while True:
            win_choice = input(f"Pilih nomor window (1-{len(windows)}): ").strip()
            if win_choice.isdigit():
                win_idx = int(win_choice)
                if 1 <= win_idx <= len(windows):
                    target_window = windows[win_idx - 1]
                    break
            print(f"Pilihan tidak valid. Masukkan angka antara 1 sampai {len(windows)}.")

        print(f"\n=> Target Window terpilih: {target_window['title']}")

    elif selected_mode == 2:
        print("\nMemindai perangkat Video / Virtual Camera yang tersedia...")
        cameras = get_available_cameras()

        if not cameras:
            print("[Warning] Tidak ada perangkat kamera / virtual camera yang terdeteksi otomatis.")
            manual_idx = input("Masukkan indeks device secara manual (default 0): ").strip()
            cam_idx = int(manual_idx) if manual_idx.isdigit() else 0
            target_camera = {"index": cam_idx, "name": f"Device #{cam_idx}"}
        else:
            print("\nDaftar Perangkat Video / Virtual Camera Tersedia:")
            print("-" * 60)
            for idx, cam in enumerate(cameras, start=1):
                dim_str = f"{cam['width']}x{cam['height']}" if cam.get('width') else "Unknown"
                print(f" [{idx:2d}] {cam['name']} (Index: {cam['index']}, Res: {dim_str})")
            print("-" * 60)

            while True:
                cam_choice = input(f"Pilih nomor kamera (1-{len(cameras)}): ").strip()
                if cam_choice.isdigit():
                    c_idx = int(cam_choice)
                    if 1 <= c_idx <= len(cameras):
                        target_camera = cameras[c_idx - 1]
                        break
                print(f"Pilihan tidak valid. Masukkan angka antara 1 sampai {len(cameras)}.")

        print(f"\n=> Target Kamera terpilih: {target_camera['name']} (Index: {target_camera['index']})")

    # 1. Jalankan Background Worker di thread terpisah (Daemon Thread)
    worker_thread = threading.Thread(
        target=background_worker, 
        args=(selected_mode, target_window, target_camera), 
        daemon=True
    )
    worker_thread.start()

    # 2. Jalankan HTTP API Server dengan Uvicorn di Thread Utama
    print("\n[Server] Menjalankan API Server di http://localhost:8000 ...")
    print("[Server] Data JSON API    : http://localhost:8000/api/mlbb-data")
    print("[Server] Live ROI Checker : http://localhost:8000/roi-checker  <-- Buka di browser untuk cek kotak ROI!")
    print("[Server] Tekan CTRL+C di terminal untuk menghentikan program.\n")

    try:
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
    except KeyboardInterrupt:
        print("\n[Server] Mematikan aplikasi...")
        is_running = False

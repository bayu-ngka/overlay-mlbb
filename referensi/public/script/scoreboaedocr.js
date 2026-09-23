let timerInterval = null;
let timerSeconds = 0;
let timerStarted = false;
let activeOcrUrl = null;

// Objek untuk menyimpan data terakhir yang valid
let lastValidData = {
    'homescore': null, 'awayscore': null,
    'bluetower': null, 'redtower': null,
    'bluelord':  null, 'redlord':   null,
    'bluegold':  null, 'redgold':   null
};

// Objek untuk melacak fase gold masing-masing tim (1 = Angka Murni, 2 = Format K)
let goldPhases = {
    'bluegold': 1,
    'redgold': 1
};

function timeToSeconds(timeStr) {
    if (!timeStr || typeof timeStr !== 'string' || !timeStr.includes(':')) return 0;
    const [minutes, seconds] = timeStr.split(':').map(Number);
    if (isNaN(minutes) || isNaN(seconds)) return 0;
    return minutes * 60 + seconds;
}

function secondsToTime(seconds) {
    if (isNaN(seconds) || seconds <= 0) return "00:00";
    const minutes = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
}

// ── TIMER: jalan sendiri tiap detik setelah distart ──────────────────────────
function startTimer(initialSeconds) {
    if (timerInterval) clearInterval(timerInterval);
    timerSeconds = initialSeconds;
    document.getElementById('timer').textContent = secondsToTime(timerSeconds);
    timerInterval = setInterval(() => {
        timerSeconds++;
        document.getElementById('timer').textContent = secondsToTime(timerSeconds);
    }, 1000);
}

// ── OCR URL ───────────────────────────────────────────────────────────────────
async function determineOcrUrl() {
    try {
        const resLocal = await fetch('http://localhost:14337/MLBB.json');
        if (resLocal.ok) return 'http://localhost:14337/MLBB.json';
    } catch (e) {
        console.log("Localhost tidak merespon, beralih ke IP Host...");
    }
    try {
        const resIp = await fetch(`/serverip.txt?t=${Date.now()}`);
        if (resIp.ok) {
            const hostIp = await resIp.text();
            const lanUrl = `http://${hostIp.trim()}:14337/MLBB.json`;
            const resLan = await fetch(lanUrl);
            if (resLan.ok) return lanUrl;
        }
    } catch (e) {
        console.log("Gagal membaca serverip.txt.");
    }
    return null;
}

// ── VALIDASI & UPDATE DATA OCR ───────────────────────────────────────────────
function processScoreboardData(id, rawValue) {
    if (rawValue === undefined || rawValue === null) return;
    let strVal = String(rawValue).trim();

    // 1. Logika Kill Score: Hanya boleh angka, maksimal lonjakan 6
    if (id === 'homescore' || id === 'awayscore') {
        if (/^\d+$/.test(strVal)) {
            let newVal = parseInt(strVal, 10);
            if (lastValidData[id] === null) {
                lastValidData[id] = strVal;
            } else {
                let oldVal = parseInt(lastValidData[id], 10);
                if (Math.abs(newVal - oldVal) <= 6) {
                    lastValidData[id] = strVal;
                } else {
                    console.log(`Kill score ${id} ditolak karena lonjakan tidak wajar: Lama ${oldVal} -> Baru ${newVal}`);
                }
            }
        }
    }
    // 2. Logika Tower & Lord: Hanya boleh satu digit angka (0-9), maksimal lonjakan 3
    else if (id === 'bluetower' || id === 'redtower' || id === 'bluelord' || id === 'redlord') {
        if (/^\d$/.test(strVal)) {
            let newVal = parseInt(strVal, 10);
            if (lastValidData[id] === null) {
                lastValidData[id] = strVal;
            } else {
                let oldVal = parseInt(lastValidData[id], 10);
                if (Math.abs(newVal - oldVal) <= 3) {
                    lastValidData[id] = strVal;
                } else {
                    console.log(`Objective ${id} ditolak karena lonjakan tidak wajar: Lama ${oldVal} -> Baru ${newVal}`);
                }
            }
        }
    }
    // 3. Logika Gold: 2 Fase Berbeda secara independen per tim
    else if (id === 'bluegold' || id === 'redgold') {
        const hasK = /[Kk]$/.test(strVal);
        
        // Phase 1: Wajib 4 digit & tidak boleh diawali angka 0 (misal: 1000 - 9999)
        const isRawNumber = /^[1-9]\d{3}$/.test(strVal); 
        const isKFormat = /^\d+(\.\d+)?[Kk]$/.test(strVal);

        // Kunci Fase 2: Jika tim sudah masuk Fase 2, tolak jika OCR tidak mendeteksi 'K'
        if (goldPhases[id] === 2 && !hasK) {
            return; // Ignore total
        }

        if (isRawNumber || isKFormat) {
            // Konversi nilai baru ke satuan asli (misal: "10.2K" -> 10200, "9500" -> 9500)
            let newAbsoluteGold = isKFormat 
                ? parseFloat(strVal.replace(/[Kk]/g, '')) * 1000 
                : parseInt(strVal, 10);
            
            // Inisialisasi awal
            if (lastValidData[id] === null) {
                lastValidData[id] = strVal.toUpperCase();
                if (isKFormat) goldPhases[id] = 2;
            } else {
                // Konversi nilai lama ke satuan asli untuk dibandingkan
                let oldAbsoluteGold = /[Kk]$/.test(lastValidData[id]) 
                    ? parseFloat(lastValidData[id].replace(/[Kk]/g, '')) * 1000 
                    : parseInt(lastValidData[id], 10);
                
                let diff = newAbsoluteGold - oldAbsoluteGold;
                
                // Smart Adjust: Kenaikan/penurunan tidak boleh lebih dari 3000 poin gold
                if (diff >= -3000 && diff <= 3000) {
                    lastValidData[id] = strVal.toUpperCase();
                    
                    // Transisi dari Fase 1 ke Fase 2 secara independen jika mendeteksi 'K' valid
                    if (isKFormat && goldPhases[id] === 1) {
                        goldPhases[id] = 2;
                    }
                } else {
                    console.log(`Gold ${id} ditolak karena selisih tidak wajar: Lama ${lastValidData[id]} -> Baru ${strVal}`);
                }
            }
        }
    }

    // Terapkan ke HTML jika kita memiliki data yang valid
    if (lastValidData[id] !== null) {
        const el = document.getElementById(id);
        if (el) el.textContent = lastValidData[id];
    }
}

// ── FETCH DATA SKOR/GOLD/TOWER/LORD: jalan tiap 1 detik ──────────────────────
async function fetchGameData() {
    try {
        if (!activeOcrUrl) {
            activeOcrUrl = await determineOcrUrl();
            if (!activeOcrUrl) return;
        }

        const response = await fetch(`${activeOcrUrl}?t=${Date.now()}`, {
            cache: 'no-store',
            headers: { 'Cache-Control': 'no-cache' }
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();

        // Peta ID elemen ke properti data OCR
        const map = {
            'homescore': data.killscore1, 'awayscore': data.killscore2,
            'bluegold':  data.gold1,      'redgold':   data.gold2,
            'bluetower': data.turret1,    'redtower':  data.turret2,
            'bluelord':  data.lord1,      'redlord':   data.lord2
        };

        // Jalankan fungsi validasi untuk setiap elemen
        for (const [id, val] of Object.entries(map)) {
            processScoreboardData(id, val);
        }

        // Tangkap timer HANYA sekali, setelah itu timer jalan sendiri
        if (!timerStarted) {
            const secs = timeToSeconds(data.timer);
            if (secs > 0) {
                console.log(`Timer ditangkap: ${data.timer} → mulai dari ${secs}s`);
                startTimer(secs);
                timerStarted = true;
            } else {
                document.getElementById('timer').textContent = "00:00";
            }
        }

    } catch (err) {
        console.error('fetchGameData error:', err);
        activeOcrUrl = null;
    }
}

// ── START ─────────────────────────────────────────────────────────────────────
fetchGameData();
setInterval(fetchGameData, 1000); // fetch data skor terus
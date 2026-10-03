/**
 * Scoreboard Overlay Engine (Golkar & MPL Indonesia Standard)
 * Supports Dynamic Match ID & Direct OCR Polling / Relay
 */

class OverlayScoreboardEngine {
  constructor() {
    this.matchId = this.getMatchIdFromUrl();
    this.matchData = null;
    this.timerInterval = null;
    this.timerSeconds = 0;
    this.timerStarted = false;
    this.sponsorIndex = 0;

    // Cache valid OCR data to protect against OCR glitches
    this.validData = {
      blueLord: 0,
      redLord: 0,
      blueTower: 0,
      redTower: 0,
      blueGold: '0',
      redGold: '0',
      blueKills: 0,
      redKills: 0
    };

    // Tracking gold phases per team: 1 = pure 4 digits, 2 = format 'K'
    this.goldPhases = {
      blue: 1,
      red: 1
    };

    this.init();
  }

  getMatchIdFromUrl() {
    const parts = window.location.pathname.split('/').filter(Boolean);
    // e.g. /overlay/scoreboard/:id
    if (parts.length >= 3 && parts[0] === 'overlay' && parts[1] === 'scoreboard') {
      return parts[2];
    }
    const params = new URLSearchParams(window.location.search);
    return params.get('match') || 'match1';
  }

  async init() {
    console.log(`[Overlay] Inisialisasi Scoreboard Golkar untuk Match: ${this.matchId}`);
    await this.fetchMatchConfig();
    this.setupSponsorRotator();
    this.startOcrSync();
  }

  async fetchMatchConfig() {
    try {
      const res = await fetch(`/api/match/${this.matchId}`);
      if (res.ok) {
        this.matchData = await res.json();
        this.applyMatchMeta();
      }
    } catch (err) {
      console.warn('[Overlay] Gagal memuat metadata match:', err);
    }
  }

  applyMatchMeta() {
    if (!this.matchData) return;

    // Tournament & Stage
    const stageEl = document.getElementById('stage-text');
    if (stageEl) {
      stageEl.textContent = `${this.matchData.tournamentName} - ${this.matchData.stage}`;
    }

    // Teams
    const blue = this.matchData.teams?.blue;
    const red = this.matchData.teams?.red;

    if (blue) {
      const nameEl = document.getElementById('blue-team-name');
      const logoEl = document.getElementById('blue-team-logo');
      if (nameEl) nameEl.textContent = blue.name;
      if (logoEl && blue.logo) logoEl.src = blue.logo;
      this.renderSeriesDots('blue-series-dots', blue.score || 0, this.matchData.format);
    }

    if (red) {
      const nameEl = document.getElementById('red-team-name');
      const logoEl = document.getElementById('red-team-logo');
      if (nameEl) nameEl.textContent = red.name;
      if (logoEl && red.logo) logoEl.src = red.logo;
      this.renderSeriesDots('red-series-dots', red.score || 0, this.matchData.format);
    }
  }

  renderSeriesDots(containerId, activeScore, format = 'BO3') {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = '';
    
    let totalWinsNeeded = 2; // Default BO3
    if (format === 'BO5') totalWinsNeeded = 3;
    if (format === 'BO7') totalWinsNeeded = 4;

    for (let i = 0; i < totalWinsNeeded; i++) {
      const dot = document.createElement('div');
      dot.className = `series-dot ${i < activeScore ? 'active' : ''}`;
      container.appendChild(dot);
    }
  }

  setupSponsorRotator() {
    const sponsors = this.matchData?.sponsors;
    if (!sponsors || sponsors.length === 0) return;

    const sponsorImg = document.getElementById('sponsor-logo');
    if (!sponsorImg) return;

    sponsorImg.src = sponsors[0].logo;

    if (sponsors.length > 1) {
      setInterval(() => {
        this.sponsorIndex = (this.sponsorIndex + 1) % sponsors.length;
        const current = sponsors[this.sponsorIndex];
        
        sponsorImg.style.opacity = '0';
        sponsorImg.style.transform = 'scale(0.92)';
        
        setTimeout(() => {
          sponsorImg.src = current.logo;
          sponsorImg.style.opacity = '1';
          sponsorImg.style.transform = 'scale(1)';
        }, 400);
      }, 7000); // Ganti tiap 7 detik
    }
  }

  startOcrSync() {
    this.pollOcrData();
    setInterval(() => this.pollOcrData(), 1000);
  }

  async pollOcrData() {
    try {
      // 1. Coba ambil dari relay server backend (/api/ocr) atau fallback langsung ke localhost:14337
      let ocrRaw = null;
      try {
        const res = await fetch(`/api/ocr?t=${Date.now()}`);
        if (res.ok) ocrRaw = await res.json();
      } catch (e) {
        // Fallback langsung ke OCR endpoint lokal
        const directRes = await fetch(`http://localhost:14337/MLBB.json?t=${Date.now()}`);
        if (directRes.ok) ocrRaw = await directRes.json();
      }

      if (ocrRaw) {
        this.processOcrData(ocrRaw);
      }
    } catch (err) {
      // OCR service mungkin belum dinyalakan, abaikan agar tidak spam console
    }
  }

  processOcrData(data) {
    // 1. Timer Logic
    if (!this.timerStarted && data.timer) {
      const totalSec = this.parseTimeToSeconds(data.timer);
      if (totalSec > 0) {
        this.startIndependentTimer(totalSec);
        this.timerStarted = true;
      }
    }

    // 2. Kills (Maksimal selisih lonjakan 6)
    this.validateAndSetStat('blueKills', data.killscore1, 6, 'blue-kills');
    this.validateAndSetStat('redKills', data.killscore2, 6, 'red-kills');

    // 3. Objectives: Turret & Lord (1 digit, max jump 3)
    this.validateAndSetObjective('blueTower', data.turret1, 'blue-tower');
    this.validateAndSetObjective('redTower', data.turret2, 'red-tower');
    this.validateAndSetObjective('blueLord', data.lord1, 'blue-lord');
    this.validateAndSetObjective('redLord', data.lord2, 'red-lord');

    // 4. Gold (Smart 2-Phase Adjuster)
    this.validateAndSetGold('blue', data.gold1, 'blue-gold');
    this.validateAndSetGold('red', data.gold2, 'red-gold');
  }

  parseTimeToSeconds(timeStr) {
    if (!timeStr || !timeStr.includes(':')) return 0;
    const parts = timeStr.split(':').map(Number);
    if (isNaN(parts[0]) || isNaN(parts[1])) return 0;
    return parts[0] * 60 + parts[1];
  }

  startIndependentTimer(startSec) {
    if (this.timerInterval) clearInterval(this.timerInterval);
    this.timerSeconds = startSec;
    this.renderTimer();
    this.timerInterval = setInterval(() => {
      this.timerSeconds++;
      this.renderTimer();
    }, 1000);
  }

  renderTimer() {
    const el = document.getElementById('game-timer');
    if (!el) return;
    const mins = Math.floor(this.timerSeconds / 60);
    const secs = this.timerSeconds % 60;
    el.textContent = `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
  }

  validateAndSetStat(key, val, maxDiff, elementId) {
    if (val === undefined || val === null) return;
    const str = String(val).trim();
    if (!/^\d+$/.test(str)) return;
    const num = parseInt(str, 10);

    const oldNum = parseInt(this.validData[key], 10) || 0;
    if (this.validData[key] === 0 || Math.abs(num - oldNum) <= maxDiff) {
      this.validData[key] = num;
      const el = document.getElementById(elementId);
      if (el) el.textContent = String(num).padStart(2, '0');
    }
  }

  validateAndSetObjective(key, val, elementId) {
    if (val === undefined || val === null) return;
    const str = String(val).trim();
    if (!/^\d$/.test(str)) return;
    const num = parseInt(str, 10);

    const oldNum = parseInt(this.validData[key], 10) || 0;
    if (this.validData[key] === 0 || Math.abs(num - oldNum) <= 3) {
      this.validData[key] = num;
      const el = document.getElementById(elementId);
      if (el) el.textContent = num;
    }
  }

  validateAndSetGold(side, val, elementId) {
    if (!val) return;
    const str = String(val).trim();
    const hasK = /[Kk]$/.test(str);
    const isRaw = /^[1-9]\d{3}$/.test(str);
    const isKFormat = /^\d+(\.\d+)?[Kk]$/.test(str);

    const phaseKey = side;
    if (this.goldPhases[phaseKey] === 2 && !hasK) {
      return; // Tolak jika sudah fase K tapi OCR kembali ke 4 digit salah
    }

    if (isRaw || isKFormat) {
      const formatted = str.toUpperCase();
      const el = document.getElementById(elementId);
      if (el) el.textContent = formatted;
      if (isKFormat) this.goldPhases[phaseKey] = 2;
    }
  }
}

// Jalankan ketika DOM siap
window.addEventListener('DOMContentLoaded', () => {
  window.overlayEngine = new OverlayScoreboardEngine();
});

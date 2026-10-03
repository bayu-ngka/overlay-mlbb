/**
 * MPL Standard 1080p Overlay Script
 * Coordinates and formats data dynamically according to official MPL broadcast standards
 */

class MplExactOverlayEngine {
  constructor() {
    this.matchId = this.getMatchId();
    this.matchData = null;
    this.timerInterval = null;
    this.timerSeconds = 0;
    this.timerStarted = false;
    this.sponsorIndex = 0;

    this.validData = {
      blueKills: 0,
      redKills: 0,
      blueGold: '0.0K',
      redGold: '0.0K',
      blueTower: 0,
      redTower: 0,
      blueLord: 0,
      redLord: 0,
      blueTurtle: 0,
      redTurtle: 0
    };

    this.goldPhases = { blue: 1, red: 1 };
    this.rawGoldValues = { blue: 0, red: 0 };

    this.init();
  }

  getMatchId() {
    const parts = window.location.pathname.split('/').filter(Boolean);
    if (parts.length >= 3 && parts[0] === 'overlay' && parts[1] === 'scoreboard') {
      return parts[2];
    }
    const params = new URLSearchParams(window.location.search);
    return params.get('match') || 'match1';
  }

  async init() {
    console.log(`[MPL Overlay 1080p] Running for Match: ${this.matchId}`);
    await this.fetchMatchData();
    this.setupSponsorCycle();
    this.startOcrPolling();
  }

  async fetchMatchData() {
    try {
      const res = await fetch(`/api/match/${this.matchId}`);
      if (res.ok) {
        this.matchData = await res.json();
        this.renderMatchDetails();
      }
    } catch (e) {
      console.warn('Gagal memuat detail match:', e);
    }
  }

  renderMatchDetails() {
    if (!this.matchData) return;

    // Right Side Metadata
    const tournamentEl = document.getElementById('meta-tournament');
    const stageEl = document.getElementById('stage-spine-text');
    const matchEl = document.getElementById('meta-match');
    const boEl = document.getElementById('meta-bo');
    const castersEl = document.getElementById('caster-names-text');

    if (tournamentEl) tournamentEl.textContent = this.matchData.tournamentName || 'MPL INDONESIA';
    if (stageEl) stageEl.textContent = this.matchData.stage || 'REGULAR SEASON';
    if (matchEl) matchEl.textContent = this.matchData.matchInfo || 'MATCH 1 - GAME 1';
    if (boEl) boEl.textContent = this.matchData.format ? `BEST OF ${this.matchData.format.replace('BO', '')}` : 'BEST OF 3';
    if (castersEl) castersEl.textContent = this.matchData.casters || 'CASTER 1 | CASTER 2';

    // Teams
    const blue = this.matchData.teams?.blue;
    const red = this.matchData.teams?.red;

    if (blue) {
      const blueName = document.getElementById('blue-name');
      const blueLogo = document.getElementById('blue-logo');
      const blueFlag = document.getElementById('blue-flag');
      if (blueName) blueName.textContent = blue.shortName || blue.name;
      if (blueLogo && blue.logo) blueLogo.src = blue.logo;
      if (blueFlag && blue.flag) blueFlag.src = blue.flag;
      this.renderSeriesTicks('blue-series-ticks', blue.seriesScore || 0, this.matchData.format);
    }

    if (red) {
      const redName = document.getElementById('red-name');
      const redLogo = document.getElementById('red-logo');
      if (redName) redName.textContent = red.shortName || red.name;
      if (redLogo && red.logo) redLogo.src = red.logo;
      this.renderSeriesTicks('red-series-ticks', red.seriesScore || 0, this.matchData.format);
    }
  }

  renderSeriesTicks(containerId, wonCount, format = 'BO3') {
    const el = document.getElementById(containerId);
    if (!el) return;
    el.innerHTML = '';
    const winsNeeded = format === 'BO5' ? 3 : (format === 'BO7' ? 4 : 2);
    for (let i = 0; i < winsNeeded; i++) {
      const tick = document.createElement('div');
      tick.className = `series-tick ${i < wonCount ? 'won' : ''}`;
      el.appendChild(tick);
    }
  }

  setupSponsorCycle() {
    const sponsors = this.matchData?.sponsors;
    if (!sponsors || sponsors.length === 0) return;

    const logoImg = document.getElementById('sponsor-logo-img');
    const labelText = document.getElementById('sponsor-label');
    if (!logoImg) return;

    logoImg.src = sponsors[0].logo;
    if (labelText && sponsors[0].tagline) labelText.textContent = sponsors[0].tagline;

    if (sponsors.length > 1) {
      setInterval(() => {
        this.sponsorIndex = (this.sponsorIndex + 1) % sponsors.length;
        const current = sponsors[this.sponsorIndex];
        logoImg.style.opacity = '0';
        setTimeout(() => {
          logoImg.src = current.logo;
          if (labelText && current.tagline) labelText.textContent = current.tagline;
          logoImg.style.opacity = '1';
        }, 300);
      }, 8000);
    }
  }

  startOcrPolling() {
    this.fetchOcr();
    setInterval(() => this.fetchOcr(), 1000);
  }

  async fetchOcr() {
    try {
      let data = null;
      try {
        const res = await fetch(`/api/ocr?t=${Date.now()}`);
        if (res.ok) data = await res.json();
      } catch (err) {
        const direct = await fetch(`http://localhost:14337/MLBB.json?t=${Date.now()}`);
        if (direct.ok) data = await direct.json();
      }

      if (data) {
        this.processOcr(data);
      }
    } catch (e) {}
  }

  processOcr(data) {
    // 1. Timer
    if (!this.timerStarted && data.timer) {
      const secs = this.timeToSeconds(data.timer);
      if (secs > 0) {
        this.startTimer(secs);
        this.timerStarted = true;
      }
    }

    // 2. Kills
    this.setNumber('blueKills', data.killscore1, 6, 'blue-kills');
    this.setNumber('redKills', data.killscore2, 6, 'red-kills');

    // 3. Objectives
    this.setObjective('blueTower', data.turret1, 'blue-tower');
    this.setObjective('redTower', data.turret2, 'red-tower');
    this.setObjective('blueLord', data.lord1, 'blue-lord');
    this.setObjective('redLord', data.lord2, 'red-lord');
    this.setObjective('blueTurtle', data.turtle1 || 0, 'blue-turtle');
    this.setObjective('redTurtle', data.turtle2 || 0, 'red-turtle');

    // 4. Gold (Formatted e.g. 5.0K)
    this.setGold('blue', data.gold1, 'blue-gold');
    this.setGold('red', data.gold2, 'red-gold');

    // 5. Gold Difference
    this.calculateGoldDiff();
  }

  timeToSeconds(timeStr) {
    if (!timeStr || !timeStr.includes(':')) return 0;
    const parts = timeStr.split(':').map(Number);
    if (isNaN(parts[0]) || isNaN(parts[1])) return 0;
    return parts[0] * 60 + parts[1];
  }

  startTimer(initialSecs) {
    if (this.timerInterval) clearInterval(this.timerInterval);
    this.timerSeconds = initialSecs;
    this.updateTimerDisplay();
    this.timerInterval = setInterval(() => {
      this.timerSeconds++;
      this.updateTimerDisplay();
    }, 1000);
  }

  updateTimerDisplay() {
    const el = document.getElementById('game-timer');
    if (!el) return;
    const m = Math.floor(this.timerSeconds / 60);
    const s = this.timerSeconds % 60;
    el.textContent = `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }

  setNumber(key, val, maxJump, elId) {
    if (val === undefined || val === null) return;
    const str = String(val).trim();
    if (!/^\d+$/.test(str)) return;
    const num = parseInt(str, 10);
    const old = parseInt(this.validData[key], 10) || 0;
    if (this.validData[key] === 0 || Math.abs(num - old) <= maxJump) {
      this.validData[key] = num;
      const el = document.getElementById(elId);
      if (el) el.textContent = num;
    }
  }

  setObjective(key, val, elId) {
    if (val === undefined || val === null) return;
    const str = String(val).trim();
    if (!/^\d$/.test(str)) return;
    const num = parseInt(str, 10);
    const el = document.getElementById(elId);
    if (el) el.textContent = num;
    this.validData[key] = num;
  }

  setGold(side, val, elId) {
    if (!val) return;
    const str = String(val).trim();
    const hasK = /[Kk]$/.test(str);
    const isRaw = /^[1-9]\d{3}$/.test(str);
    const isKFormat = /^\d+(\.\d+)?[Kk]$/.test(str);

    if (this.goldPhases[side] === 2 && !hasK) return;

    if (isRaw || isKFormat) {
      let formatted = str.toUpperCase();
      let absoluteVal = 0;
      if (isKFormat) {
        absoluteVal = parseFloat(str.replace(/[Kk]/g, '')) * 1000;
      } else {
        absoluteVal = parseInt(str, 10);
        // format raw to decimal K if >= 1000 (misal 5000 -> 5.0K)
        formatted = (absoluteVal / 1000).toFixed(1) + 'K';
      }

      this.rawGoldValues[side] = absoluteVal;
      const el = document.getElementById(elId);
      if (el) el.textContent = formatted;
      if (isKFormat) this.goldPhases[side] = 2;
    }
  }

  calculateGoldDiff() {
    const diffEl = document.getElementById('gold-diff-val');
    if (!diffEl) return;
    const diff = Math.abs(this.rawGoldValues.blue - this.rawGoldValues.red);
    const formattedDiff = diff >= 1000 ? `${(diff / 1000).toFixed(1)}K` : `+${diff}`;
    diffEl.textContent = `+${diff >= 1000 ? (diff / 1000).toFixed(1) + 'K' : diff}`;
  }
}

window.addEventListener('DOMContentLoaded', () => {
  new MplExactOverlayEngine();
});

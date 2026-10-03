const express = require('express');
const cors = require('cors');
const http = require('http');
const path = require('path');
const fs = require('fs');
const WebSocket = require('ws');

const app = express();
const server = http.createServer(app);
const PORT = process.env.PORT || 4000;

// Setup WebSocket Server
const wss = new WebSocket.Server({ server });

app.use(cors());
app.use(express.json());

// Serve static assets (CSS, JS, Logos, Sponsors)
app.use(express.static(path.join(__dirname, 'public')));

// Database & Data file paths
const MATCHES_FILE = path.join(__dirname, 'data', 'matches.json');
const CONTROL_STATE_FILE = path.join(__dirname, 'data', 'control_state.json');
const SPONSORS_FILE = path.join(__dirname, 'data', 'sponsors.json');
const HEROES_FILE = path.join(__dirname, 'data', 'heroes.json');
const DRAFT_STATE_FILE = path.join(__dirname, 'data', 'draft_state.json');

// Default initial control state
const defaultControlState = {
  bo: 3,                 // 1, 3, 5
  winLeft: 0,            // Series score kiri
  winRight: 1,           // Series score kanan
  teamLeft: "TLI",       // Inisial tim kiri
  teamRight: "ONI",      // Inisial tim kanan
  mapName: "BROKEN WALL",
  timerCutout: false,    // true: tembus pandang in-game, false: normal
  sponsorMode: "auto",   // auto: rotasi, atau id sponsor
  activeSponsorId: null,
  ocrUrl: "http://192.168.43.253:14337/MLBB.json" // URL JSON endpoint OCR (LAN / Localhost)
};

// Default initial draft state (10 Ban, 10 Pick resmi MLBB)
const defaultDraftState = {
  currentPhaseIndex: 0,
  timer: 45,
  timerRunning: false,
  blueBans: ["", "", "", "", ""],
  redBans: ["", "", "", "", ""],
  bluePicks: ["", "", "", "", ""],
  redPicks: ["", "", "", "", ""],
  previewHero: null // Hero yang sedang di-preview sebelum di-lock
};

// Urutan tahapan resmi Draft MLBB (Mendukung Single & Double Pick bersamaan)
const DRAFT_PHASES = [
  // Ban Tahap 1 (1 hero bergantian)
  { index: 0, type: "BANNING", side: "blue", action: "ban", targets: [{ slot: 0, label: "Blue Ban 1", player: 1 }], label: "Blue Ban 1" },
  { index: 1, type: "BANNING", side: "red", action: "ban", targets: [{ slot: 0, label: "Red Ban 1", player: 1 }], label: "Red Ban 1" },
  { index: 2, type: "BANNING", side: "blue", action: "ban", targets: [{ slot: 1, label: "Blue Ban 2", player: 2 }], label: "Blue Ban 2" },
  { index: 3, type: "BANNING", side: "red", action: "ban", targets: [{ slot: 1, label: "Red Ban 2", player: 2 }], label: "Red Ban 2" },
  { index: 4, type: "BANNING", side: "blue", action: "ban", targets: [{ slot: 2, label: "Blue Ban 3", player: 3 }], label: "Blue Ban 3" },
  { index: 5, type: "BANNING", side: "red", action: "ban", targets: [{ slot: 2, label: "Red Ban 3", player: 3 }], label: "Red Ban 3" },

  // Pick Tahap 1 (Single & Double Pick)
  { index: 6, type: "PICKING", side: "blue", action: "pick", targets: [{ slot: 0, label: "Blue Pick 1", player: 1 }], label: "Blue Pick 1" },
  { index: 7, type: "PICKING", side: "red", action: "pick", targets: [{ slot: 0, label: "Red Pick 1", player: 1 }, { slot: 1, label: "Red Pick 2", player: 2 }], label: "Red Pick 1 & 2" },
  { index: 8, type: "PICKING", side: "blue", action: "pick", targets: [{ slot: 1, label: "Blue Pick 2", player: 2 }, { slot: 2, label: "Blue Pick 3", player: 3 }], label: "Blue Pick 2 & 3" },
  { index: 9, type: "PICKING", side: "red", action: "pick", targets: [{ slot: 2, label: "Red Pick 3", player: 3 }], label: "Red Pick 3" },

  // Ban Tahap 2 (1 hero bergantian)
  { index: 10, type: "BANNING", side: "red", action: "ban", targets: [{ slot: 3, label: "Red Ban 4", player: 4 }], label: "Red Ban 4" },
  { index: 11, type: "BANNING", side: "blue", action: "ban", targets: [{ slot: 3, label: "Blue Ban 4", player: 4 }], label: "Blue Ban 4" },
  { index: 12, type: "BANNING", side: "red", action: "ban", targets: [{ slot: 4, label: "Red Ban 5", player: 5 }], label: "Red Ban 5" },
  { index: 13, type: "BANNING", side: "blue", action: "ban", targets: [{ slot: 4, label: "Blue Ban 5", player: 5 }], label: "Blue Ban 5" },

  // Pick Tahap 2 (Single & Double Pick)
  { index: 14, type: "PICKING", side: "red", action: "pick", targets: [{ slot: 3, label: "Red Pick 4", player: 4 }], label: "Red Pick 4" },
  { index: 15, type: "PICKING", side: "blue", action: "pick", targets: [{ slot: 3, label: "Blue Pick 4", player: 4 }, { slot: 4, label: "Blue Pick 5", player: 5 }], label: "Blue Pick 4 & 5" },
  { index: 16, type: "PICKING", side: "red", action: "pick", targets: [{ slot: 4, label: "Red Pick 5", player: 5 }], label: "Red Pick 5" },

  // Preparation / Selesai
  { index: 17, type: "PREPARATION", side: "none", action: "none", targets: [], label: "Preparation Phase" }
];

// Helper state loaders & savers
function getControlState() {
  try {
    if (fs.existsSync(CONTROL_STATE_FILE)) {
      return { ...defaultControlState, ...JSON.parse(fs.readFileSync(CONTROL_STATE_FILE, 'utf-8')) };
    }
  } catch (e) {
    console.error('Error reading control_state.json:', e);
  }
  return { ...defaultControlState };
}

function saveControlState(state) {
  try {
    fs.writeFileSync(CONTROL_STATE_FILE, JSON.stringify(state, null, 2), 'utf-8');
  } catch (e) {
    console.error('Error writing control_state.json:', e);
  }
}

function getDraftState() {
  try {
    if (fs.existsSync(DRAFT_STATE_FILE)) {
      return { ...defaultDraftState, ...JSON.parse(fs.readFileSync(DRAFT_STATE_FILE, 'utf-8')) };
    }
  } catch (e) {
    console.error('Error reading draft_state.json:', e);
  }
  return { ...defaultDraftState };
}

function saveDraftState(state) {
  try {
    fs.writeFileSync(DRAFT_STATE_FILE, JSON.stringify(state, null, 2), 'utf-8');
  } catch (e) {
    console.error('Error writing draft_state.json:', e);
  }
}

let currentControlState = getControlState();
let currentDraftState = getDraftState();

// Timer ticker server-side untuk draft
let draftTimerInterval = null;

function startDraftTimer() {
  if (draftTimerInterval) clearInterval(draftTimerInterval);
  currentDraftState.timerRunning = true;
  saveDraftState(currentDraftState);
  broadcastState('DRAFT_STATE_UPDATED', currentDraftState);

  draftTimerInterval = setInterval(() => {
    if (currentDraftState.timer > 0 && currentDraftState.timerRunning) {
      currentDraftState.timer--;
      broadcastState('DRAFT_TIMER_TICK', { timer: currentDraftState.timer });
      if (currentDraftState.timer === 0) {
        currentDraftState.timerRunning = false;
        clearInterval(draftTimerInterval);
        saveDraftState(currentDraftState);
        broadcastState('DRAFT_STATE_UPDATED', currentDraftState);
      }
    } else {
      currentDraftState.timerRunning = false;
      clearInterval(draftTimerInterval);
    }
  }, 1000);
}

function pauseDraftTimer() {
  currentDraftState.timerRunning = false;
  if (draftTimerInterval) clearInterval(draftTimerInterval);
  saveDraftState(currentDraftState);
  broadcastState('DRAFT_STATE_UPDATED', currentDraftState);
}

function resetDraftTimer(seconds = 45) {
  currentDraftState.timer = seconds;
  saveDraftState(currentDraftState);
  broadcastState('DRAFT_STATE_UPDATED', currentDraftState);
}

// -------------------------------------------------------------
// SISTEM DATA TUNGGAL SPONSOR & ROTASI SINKRON
// -------------------------------------------------------------
function getSponsorsList() {
  try {
    if (fs.existsSync(SPONSORS_FILE)) {
      return JSON.parse(fs.readFileSync(SPONSORS_FILE, 'utf-8'));
    }
  } catch (e) {
    console.error('Error reading sponsors.json:', e);
  }
  return [];
}

let sponsorsList = getSponsorsList();
let currentSponsorIndex = 0;
let sponsorTimer = null;

function getCurrentSponsorItem() {
  if (!sponsorsList || sponsorsList.length === 0) return null;
  return sponsorsList[currentSponsorIndex] || sponsorsList[0];
}

function scheduleNextSponsor() {
  if (sponsorTimer) clearTimeout(sponsorTimer);
  sponsorsList = getSponsorsList();
  if (!sponsorsList || sponsorsList.length === 0) return;

  const currentItem = sponsorsList[currentSponsorIndex] || sponsorsList[0];
  const duration = currentItem.duration || 5000;

  sponsorTimer = setTimeout(() => {
    currentSponsorIndex = (currentSponsorIndex + 1) % sponsorsList.length;
    const nextItem = sponsorsList[currentSponsorIndex];
    broadcastState('SPONSOR_ROTATION', {
      index: currentSponsorIndex,
      sponsor: nextItem,
      total: sponsorsList.length
    });
    scheduleNextSponsor();
  }, duration);
}

// Mulai timer sinkronisasi sponsor pertama kali
scheduleNextSponsor();

// Broadcast event ke semua koneksi WebSocket yang aktif (OBS & Dashboard)
function broadcastState(eventType, data) {
  const payload = JSON.stringify({ type: eventType, data: data, timestamp: Date.now() });
  wss.clients.forEach(client => {
    if (client.readyState === WebSocket.OPEN) {
      client.send(payload);
    }
  });
}

// Handler WebSocket
wss.on('connection', (ws) => {
  // Kirim state saat ini, sponsor aktif, dan draft state saat client baru terkoneksi
  ws.send(JSON.stringify({
    type: 'INIT_STATE',
    data: currentControlState,
    draftData: currentDraftState,
    draftPhases: DRAFT_PHASES,
    currentSponsor: {
      index: currentSponsorIndex,
      sponsor: getCurrentSponsorItem(),
      total: sponsorsList.length
    }
  }));

  ws.on('message', (message) => {
    try {
      const msg = JSON.parse(message);
      if (msg.type === 'UPDATE_CONTROL') {
        currentControlState = { ...currentControlState, ...msg.data };
        saveControlState(currentControlState);
        broadcastState('STATE_UPDATED', currentControlState);
      } else if (msg.type === 'UPDATE_DRAFT') {
        currentDraftState = { ...currentDraftState, ...msg.data };
        saveDraftState(currentDraftState);
        broadcastState('DRAFT_STATE_UPDATED', currentDraftState);
      } else if (msg.type === 'DRAFT_START_TIMER') {
        startDraftTimer();
      } else if (msg.type === 'DRAFT_PAUSE_TIMER') {
        pauseDraftTimer();
      } else if (msg.type === 'DRAFT_RESET_TIMER') {
        resetDraftTimer(msg.seconds || 45);
      } else if (msg.type === 'DRAFT_RESET_ALL') {
        if (draftTimerInterval) clearInterval(draftTimerInterval);
        currentDraftState = { ...defaultDraftState };
        saveDraftState(currentDraftState);
        broadcastState('DRAFT_STATE_UPDATED', currentDraftState);
      }
    } catch (err) {
      console.error('WS Message Error:', err);
    }
  });
});

// Helper to get matches data
function getMatchesData() {
  try {
    if (fs.existsSync(MATCHES_FILE)) {
      return JSON.parse(fs.readFileSync(MATCHES_FILE, 'utf-8'));
    }
  } catch (err) {
    console.error('Error reading matches.json:', err);
  }
  return { matches: {} };
}

// Helper to save matches data
function saveMatchesData(data) {
  try {
    fs.writeFileSync(MATCHES_FILE, JSON.stringify(data, null, 2), 'utf-8');
  } catch (err) {
    console.error('Error writing matches.json:', err);
  }
}

// -------------------------------------------------------------
// DYNAMIC OVERLAY ROUTES (OBS Browser Sources)
// -------------------------------------------------------------

// Route 1: Dynamic overlay with matchId param -> /overlay/scoreboard/:matchId
app.get('/overlay/scoreboard/:matchId', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'scoreboard_exact.html'));
});

// Route 2: Default fallback scoreboard
app.get('/overlay/scoreboard', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'scoreboard_exact.html'));
});

// -------------------------------------------------------------
// API ENDPOINTS
// -------------------------------------------------------------

// Get single match info by ID
app.get('/api/match/:matchId', (req, res) => {
  const { matchId } = req.params;
  const db = getMatchesData();
  const match = db.matches[matchId] || db.matches['match1'];
  if (!match) {
    return res.status(404).json({ error: 'Match tidak ditemukan' });
  }
  res.json(match);
});

// Update match info (Used by future Control Panel)
app.post('/api/match/:matchId', (req, res) => {
  const { matchId } = req.params;
  const db = getMatchesData();
  db.matches[matchId] = {
    ...(db.matches[matchId] || {}),
    ...req.body,
    id: matchId
  };
  saveMatchesData(db);
  res.json({ success: true, match: db.matches[matchId] });
});

// OCR Relay endpoint: mem-proxy request ke OCR engine (IP LAN atau localhost)
app.get('/api/ocr', async (req, res) => {
  const configuredUrl = currentControlState.ocrUrl ? currentControlState.ocrUrl.trim() : '';
  const ocrCandidates = [];
  if (configuredUrl) {
    ocrCandidates.push(configuredUrl);
  }
  ocrCandidates.push(
    'http://192.168.43.253:14337/MLBB.json',
    'http://localhost:14337/MLBB.json',
    'http://127.0.0.1:14337/MLBB.json'
  );

  try {
    const fetch = (...args) => import('node-fetch').then(({ default: fetch }) => fetch(...args));
    for (const url of ocrCandidates) {
      try {
        const ocrRes = await fetch(url, { timeout: 1000 });
        if (ocrRes.ok) {
          const data = await ocrRes.json();
          return res.json(data);
        }
      } catch (err) {
        // Coba kandidat berikutnya
      }
    }
  } catch (e) {
    // OCR offline atau gagal
  }

  // Jika OCR lokal tidak aktif, kembalikan status standby / mock
  res.json({
    timer: "00:00",
    killscore1: "0",
    killscore2: "0",
    turret1: "0",
    turret2: "0",
    lord1: "0",
    lord2: "0",
    gold1: "0",
    gold2: "0",
    status: "ocr_standby"
  });
});

// -------------------------------------------------------------
// CONTROL PANEL API & ROUTES
// -------------------------------------------------------------
app.get('/api/control', (req, res) => {
  res.json(currentControlState);
});

app.post('/api/control', (req, res) => {
  currentControlState = { ...currentControlState, ...req.body };
  saveControlState(currentControlState);
  broadcastState('STATE_UPDATED', currentControlState);
  res.json({ success: true, state: currentControlState });
});

// Endpoint Data Sponsor Bersama (Single Source of Truth)
app.get('/api/sponsors', (req, res) => {
  res.json(getSponsorsList());
});

// Endpoint Data Heroes (Roster Lengkap beserta Role)
app.get('/api/heroes', (req, res) => {
  try {
    if (fs.existsSync(HEROES_FILE)) {
      return res.json(JSON.parse(fs.readFileSync(HEROES_FILE, 'utf-8')));
    }
  } catch (e) {
    console.error('Error reading heroes.json:', e);
  }
  res.json([]);
});

// Endpoint Data Draft State & Phases
app.get('/api/draft', (req, res) => {
  res.json({
    state: currentDraftState,
    phases: DRAFT_PHASES
  });
});

app.post('/api/draft', (req, res) => {
  currentDraftState = { ...currentDraftState, ...req.body };
  saveDraftState(currentDraftState);
  broadcastState('DRAFT_STATE_UPDATED', currentDraftState);
  res.json({ success: true, state: currentDraftState });
});

app.get('/control', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'control.html'));
});

// Overlay Ban & Pick Route
app.get('/overlay/bp', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'bp1.html'));
});

// Status Info
app.get('/api/status', (req, res) => {
  res.json({
    status: 'online',
    system: 'Esport Broadcast Overlay Engine (Golkar Theme)',
    activeRoutes: [
      '/sb1.html (Active Scoreboard)',
      '/control.html (Dashboard Control)',
      '/overlay/scoreboard/:matchId',
      '/api/match/:matchId',
      '/api/ocr',
      '/api/control'
    ]
  });
});

server.listen(PORT, '0.0.0.0', () => {
  const os = require('os');
  const networkInterfaces = os.networkInterfaces();
  const lanIps = [];

  Object.keys(networkInterfaces).forEach((ifaceName) => {
    networkInterfaces[ifaceName].forEach((iface) => {
      if (iface.family === 'IPv4' && !iface.internal) {
        lanIps.push(iface.address);
      }
    });
  });

  console.log(`=======================================================`);
  console.log(`🚀 ESPORT OVERLAY SERVER AKTIF DI PORT: ${PORT}`);
  console.log(`📡 Localhost : http://localhost:${PORT}/control.html`);
  if (lanIps.length > 0) {
    lanIps.forEach(ip => {
      console.log(`🌐 Akses LAN  : http://${ip}:${PORT}/control.html`);
    });
  }
  console.log(`📡 Overlay BP : http://localhost:${PORT}/bp1.html`);
  console.log(`📡 Scoreboard : http://localhost:${PORT}/sb1.html`);
  console.log(`=======================================================`);
});

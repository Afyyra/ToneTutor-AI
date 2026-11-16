// ToneTutor browser webcam piano (Streamlit components v2 module).
//
// The camera, MediaPipe hand tracking and tap detection all run in the visitor's browser,
// so the webcam piano also works when ToneTutor is hosted online. Only detected note names
// are sent to Python. Video and hand landmarks never leave the device.
//
// The keyboard layout and tap detector are ports of table_piano_core.py and are exported
// so tests/test_browser_webcam.py can check them against the Python originals with Node.

const TASKS_VERSION = '0.10.21';
const TASKS_BASE = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${TASKS_VERSION}`;
const MODEL_URL = 'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task';
export const LAYOUT_W = 1000;
export const LAYOUT_H = 480;
const TIPS = [4, 8, 12, 16, 20];
const TIP_TO_MCP = { 4: 2, 8: 5, 12: 9, 16: 13, 20: 17 };
const NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
const DEFAULT_PARAMS = { min_down_y: 6.0, min_depth_delta: 0.014, min_y_velocity: 90.0, min_z_velocity: 0.16 };

// ---------- pure logic (ported from table_piano_core.py) ----------

export function buildLayout(width = LAYOUT_W, height = LAYOUT_H, octaves = 2) {
  const whiteClasses = ['C', 'D', 'E', 'F', 'G', 'A', 'B'];
  const blackAfter = { 0: 'C#', 1: 'D#', 3: 'F#', 4: 'G#', 5: 'A#' };
  const unit = width / (7 * octaves);
  const whites = [], blacks = [];
  for (let octave = 4; octave < 4 + octaves; octave++) {
    whiteClasses.forEach((name, offset) => {
      const i = (octave - 4) * 7 + offset, x1 = i * unit, x2 = (i + 1) * unit;
      whites.push([name + octave, x1, 0, x2, height]);
      if (offset in blackAfter) {
        const bw = unit * 0.59;
        blacks.push([blackAfter[offset] + octave, x2 - bw / 2, 0, x2 + bw / 2, height * 0.60]);
      }
    });
  }
  return { width, height, whites, blacks };
}

export function noteAt(layout, x, y) {
  if (!(x >= 0 && x <= layout.width && y >= 0 && y <= layout.height)) return null;
  for (const [note, x1, y1, x2, y2] of layout.blacks.concat(layout.whites)) {
    if (x1 <= x && x < x2 && y1 <= y && y < y2) return note;
  }
  return null;
}

// One press per downstroke: approach, settle on the same key, then lift to rearm.
export function makeTapDetector(params = {}) {
  const P = Object.assign({}, DEFAULT_PARAMS, params);
  const releaseY = 5.0, releaseZ = 0.010, settleY = 3.0, cooldown = 0.20, settleWindow = 0.17;
  const states = new Map();
  return {
    states,
    setParams(p) { Object.assign(P, DEFAULT_PARAMS, p || {}); },
    forgetMissing(visible) { for (const id of [...states.keys()]) if (!visible.has(id)) states.delete(id); },
    update(id, note, y, z, t) {
      const s = states.get(id);
      if (!s) { states.set(id, { y, z, t, armed: true, pending: null, pendingSince: 0, lastTrigger: -1e9, lifts: 0 }); return null; }
      const dy = y - s.y, dz = z - s.z, dt = Math.max(t - s.t, 0.001);
      s.y = y; s.z = z; s.t = t;
      if (note === null) { s.armed = true; s.pending = null; s.lifts = 0; return null; }
      if (s.pending && (s.pending !== note || t - s.pendingSince > settleWindow)) s.pending = null;
      const lifted = dy <= -releaseY || dz <= -releaseZ;
      if (!s.armed) {
        if (lifted) {
          s.lifts += 1;
          if (s.lifts >= 1 && t - s.lastTrigger >= cooldown) { s.armed = true; s.lifts = 0; }
        } else s.lifts = 0;
        return null;
      }
      if (t - s.lastTrigger < cooldown) return null;
      const downward = (dy >= P.min_down_y && dy / dt >= P.min_y_velocity) ||
                       (dz >= P.min_depth_delta && dz / dt >= P.min_z_velocity);
      if (s.pending === null) {
        if (downward && dt < 0.25) { s.pending = note; s.pendingSince = t; }
        return null;
      }
      if (Math.abs(dy) <= settleY && Math.abs(dz) <= P.min_depth_delta * 0.8) {
        s.pending = null; s.armed = false; s.lastTrigger = t;
        return note;
      }
      return null;
    },
  };
}

// Perspective transform from four source points to four destination points (h33 = 1).
export function homography(src, dst) {
  const A = [], b = [];
  for (let i = 0; i < 4; i++) {
    const [x, y] = src[i], [u, v] = dst[i];
    A.push([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.push(u);
    A.push([0, 0, 0, x, y, 1, -v * x, -v * y]); b.push(v);
  }
  for (let c = 0; c < 8; c++) {           // Gaussian elimination with partial pivoting
    let p = c;
    for (let r = c + 1; r < 8; r++) if (Math.abs(A[r][c]) > Math.abs(A[p][c])) p = r;
    if (Math.abs(A[p][c]) < 1e-12) return null;
    [A[c], A[p]] = [A[p], A[c]]; [b[c], b[p]] = [b[p], b[c]];
    for (let r = 0; r < 8; r++) {
      if (r === c) continue;
      const f = A[r][c] / A[c][c];
      for (let k = c; k < 8; k++) A[r][k] -= f * A[c][k];
      b[r] -= f * b[c];
    }
  }
  return b.map((v, i) => v / A[i][i]).concat([1]);
}

export function applyH(h, x, y) {
  const d = h[6] * x + h[7] * y + h[8];
  return [(h[0] * x + h[1] * y + h[2]) / d, (h[3] * x + h[4] * y + h[5]) / d];
}

export function polygonArea(pts) {
  let a = 0;
  for (let i = 0; i < pts.length; i++) {
    const [x1, y1] = pts[i], [x2, y2] = pts[(i + 1) % pts.length];
    a += x1 * y2 - x2 * y1;
  }
  return Math.abs(a) / 2;
}

function midi(note) {
  const m = /^([A-G]#?)(\d)$/.exec(note);
  return m ? NAMES.indexOf(m[1]) + (Number(m[2]) + 1) * 12 : 60;
}

// ---------- browser component ----------

function createController(root) {
  const $ = (s) => root.querySelector(s);
  const video = $('video'), canvas = $('canvas'), ctx = canvas.getContext('2d');
  const statusEl = $('.ttw-status');
  const btn = { start: $('[data-act=start]'), cal: $('[data-act=cal]'), def: $('[data-act=def]'), stop: $('[data-act=stop]') };
  const layout = buildLayout();
  const corners = [[0, 0], [LAYOUT_W, 0], [LAYOUT_W, LAYOUT_H], [0, LAYOUT_H]];
  const S = {
    data: {}, setState: null, stream: null, landmarker: null, running: false, starting: false,
    raf: 0, H: null, Hinv: null, clicks: null, dots: [], taps: [], seq: 0,
    nonce: Math.random().toString(36).slice(2, 10) + Date.now().toString(36),
    lastVideoTime: -1, lastTs: -1, played: null, playedUntil: 0, audio: null, autostarted: false,
    detector: makeTapDetector(),
  };

  const setStatus = (text) => { statusEl.textContent = text; };
  const updateButtons = () => {
    btn.start.disabled = S.running || S.starting;
    btn.stop.disabled = !S.running;
    btn.cal.disabled = !S.running;
    btn.def.disabled = !S.running;
  };

  function setCorners(pts) {
    const h = homography(pts, corners), hi = homography(corners, pts);
    if (!h || !hi) { setStatus('Those corners do not form a usable area. Try again.'); return false; }
    S.H = h; S.Hinv = hi; S.detector.states.clear();
    return true;
  }
  function defaultCorners() {
    const w = canvas.width, h = canvas.height;
    setCorners([[w * 0.045, h * 0.49], [w * 0.955, h * 0.49], [w * 0.955, h * 0.94], [w * 0.045, h * 0.94]]);
  }

  function playSound(note) {
    try {
      S.audio = S.audio || new (window.AudioContext || window.webkitAudioContext)();
      if (S.audio.state === 'suspended') S.audio.resume();
      const osc = S.audio.createOscillator(), gain = S.audio.createGain(), now = S.audio.currentTime;
      osc.type = 'sine'; osc.frequency.value = 440 * Math.pow(2, (midi(note) - 69) / 12);
      osc.connect(gain); gain.connect(S.audio.destination);
      gain.gain.setValueAtTime(0.001, now);
      gain.gain.exponentialRampToValueAtTime(0.26, now + 0.014);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.55);
      osc.start(now); osc.stop(now + 0.57);
    } catch (err) { /* audio is optional */ }
  }

  function onTap(note) {
    playSound(note);
    S.played = note; S.playedUntil = performance.now() + 220;
    S.taps.push({ id: ++S.seq, note });
    if (S.taps.length > 40) S.taps.shift();
    if (S.setState) S.setState('taps', JSON.stringify({ nonce: S.nonce, taps: S.taps }));
    setStatus('Played ' + note);
  }

  function drawPolygon(pts, fill, stroke) {
    ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]);
    for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
    ctx.closePath(); ctx.fillStyle = fill; ctx.fill();
    if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = 1.2; ctx.stroke(); }
  }
  function drawKeys(nowMs) {
    if (!S.Hinv) return;
    const target = S.data.target || '', hide = !!S.data.hideLabels;
    const flash = nowMs < S.playedUntil ? S.played : null;
    const size = Math.max(10, canvas.width / 85);
    ctx.font = `600 ${size}px sans-serif`; ctx.textAlign = 'center';
    const quad = (x1, y1, x2, y2) => [[x1, y1], [x2, y1], [x2, y2], [x1, y2]].map(([x, y]) => applyH(S.Hinv, x, y));
    for (const [note, x1, y1, x2, y2] of layout.whites) {
      const fill = note === flash ? 'rgba(105,238,155,0.62)' : note === target ? 'rgba(120,180,252,0.55)' : 'rgba(255,255,255,0.20)';
      drawPolygon(quad(x1, y1, x2, y2), fill, 'rgba(30,34,51,0.75)');
      if (!hide) { const [lx, ly] = applyH(S.Hinv, (x1 + x2) / 2, y2 - 18); ctx.fillStyle = '#1d2233'; ctx.fillText(note, lx, ly); }
    }
    for (const [note, x1, y1, x2, y2] of layout.blacks) {
      const fill = note === flash ? 'rgba(65,205,115,0.78)' : note === target ? 'rgba(90,120,235,0.78)' : 'rgba(20,25,37,0.55)';
      drawPolygon(quad(x1, y1, x2, y2), fill, null);
    }
  }

  function handleHands(res, t) {
    const seen = new Set(), dots = [];
    const hands = res.landmarks || [];
    const sides = res.handedness || res.handednesses || [];
    hands.forEach((lms, hi) => {
      const side = ((sides[hi] && sides[hi][0] && sides[hi][0].categoryName) || 'hand') + '_' + hi;
      for (const tip of TIPS) {
        const lm = lms[tip], base = lms[TIP_TO_MCP[tip]];
        const x = (1 - lm.x) * canvas.width, y = lm.y * canvas.height;   // mirrored, as the learner sees it
        const [kx, ky] = applyH(S.H, x, y);
        const id = side + '_' + tip;
        seen.add(id);
        const played = S.detector.update(id, noteAt(layout, kx, ky), ky, lm.z - base.z, t);
        dots.push([x, y, !!played]);
        if (played) onTap(played);
      }
    });
    S.detector.forgetMissing(seen);
    S.dots = dots;
  }

  function drawOverlay() {
    for (const [x, y, hit] of S.dots) {
      ctx.beginPath(); ctx.arc(x, y, Math.max(5, canvas.width / 200), 0, Math.PI * 2);
      ctx.fillStyle = hit ? '#3cff5a' : '#ffb432'; ctx.fill();
    }
    if (S.clicks) {
      S.clicks.forEach(([x, y], i) => {
        ctx.beginPath(); ctx.arc(x, y, 9, 0, Math.PI * 2); ctx.fillStyle = '#ffc800'; ctx.fill();
        ctx.fillStyle = '#fff'; ctx.fillText(String(i + 1), x + 16, y + 4);
      });
    }
  }

  function drawIdle(message) {
    ctx.fillStyle = '#151a24'; ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = '#e8e8ec'; ctx.textAlign = 'center';
    ctx.font = `600 ${Math.max(16, canvas.width / 45)}px sans-serif`;
    ctx.fillText(message, canvas.width / 2, canvas.height / 2);
  }

  function loop() {
    if (!S.running) return;
    S.raf = requestAnimationFrame(loop);
    if (video.readyState < 2) return;
    const w = canvas.width, h = canvas.height, nowMs = performance.now();
    ctx.save(); ctx.translate(w, 0); ctx.scale(-1, 1); ctx.drawImage(video, 0, 0, w, h); ctx.restore();
    if (video.currentTime !== S.lastVideoTime && S.landmarker) {
      S.lastVideoTime = video.currentTime;
      const ts = Math.max(S.lastTs + 1, Math.round(nowMs)); S.lastTs = ts;
      try { handleHands(S.landmarker.detectForVideo(video, ts), nowMs / 1000); }
      catch (err) { setStatus('Hand tracking error: ' + (err && err.message)); }
    }
    drawKeys(nowMs);
    drawOverlay();
  }

  async function loadLandmarker() {
    const vision = await import(`${TASKS_BASE}/vision_bundle.mjs`);
    const files = await vision.FilesetResolver.forVisionTasks(`${TASKS_BASE}/wasm`);
    const options = (delegate) => ({
      baseOptions: { modelAssetPath: MODEL_URL, delegate }, runningMode: 'VIDEO', numHands: 2,
      minHandDetectionConfidence: 0.60, minHandPresenceConfidence: 0.55, minTrackingConfidence: 0.60,
    });
    try { return await vision.HandLandmarker.createFromOptions(files, options('GPU')); }
    catch (err) { return await vision.HandLandmarker.createFromOptions(files, options('CPU')); }
  }

  function stopTracks() {
    if (S.stream) S.stream.getTracks().forEach((t) => t.stop());
    S.stream = null; video.srcObject = null;
  }

  async function start() {
    if (S.running || S.starting) return;
    S.starting = true; updateButtons();
    try {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw new Error('this browser cannot open a camera here. Use Chrome or Edge on an https:// or localhost page.');
      }
      setStatus('Asking for camera permission...');
      S.stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: 'user' }, audio: false });
      video.srcObject = S.stream;
      await video.play();
      canvas.width = video.videoWidth || 1280; canvas.height = video.videoHeight || 720;
      if (!S.H) defaultCorners();
      setStatus('Loading hand tracking (first time can take a few seconds)...');
      if (!S.landmarker) S.landmarker = await loadLandmarker();
      S.running = true;
      if (S.setState) S.setState('status', 'running');
      setStatus('Camera on. Keys are drawn over the lower part of the picture. Calibrate to fit your table.');
      loop();
    } catch (err) {
      stopTracks();
      const name = err && err.name;
      const hint = name === 'NotAllowedError' ? 'camera permission was blocked. Allow the camera in the address bar and try again.'
        : name === 'NotReadableError' ? 'the camera is busy. Close other apps or windows using it and try again.'
        : name === 'NotFoundError' ? 'no camera was found.' : (err && err.message) || String(err);
      setStatus('Camera could not start: ' + hint);
      drawIdle('Camera off');
    } finally {
      S.starting = false; updateButtons();
    }
  }

  function stop(fromUser) {
    S.running = false;
    cancelAnimationFrame(S.raf);
    stopTracks();
    S.dots = []; S.clicks = null; S.detector.states.clear();
    if (fromUser && S.setState) S.setState('status', 'stopped');
    drawIdle('Camera off · press Start camera');
    setStatus('Camera off');
    updateButtons();
  }

  canvas.addEventListener('click', (ev) => {
    if (!S.clicks) return;
    const r = canvas.getBoundingClientRect();
    S.clicks.push([(ev.clientX - r.left) * canvas.width / r.width, (ev.clientY - r.top) * canvas.height / r.height]);
    const names = ['top-right', 'bottom-right', 'bottom-left'];
    if (S.clicks.length < 4) { setStatus('Now click the ' + names[S.clicks.length - 1] + ' corner.'); return; }
    const pts = S.clicks; S.clicks = null;
    if (polygonArea(pts) < 2000) { setStatus('That area is too small. Press Calibrate corners and try again.'); return; }
    if (setCorners(pts)) setStatus('Calibrated. Tap a key and lift your finger before the next one.');
  });
  btn.start.onclick = () => start();
  btn.stop.onclick = () => stop(true);
  btn.def.onclick = () => { S.clicks = null; defaultCorners(); setStatus('Using the default area in the lower part of the picture.'); };
  btn.cal.onclick = () => { S.clicks = []; setStatus('Click the top-left corner of your play area, as you see it on screen.'); };

  drawIdle('Camera off · press Start camera');
  updateButtons();

  return {
    S,
    apply(data, setStateValue) {
      S.data = data || {}; S.setState = setStateValue;
      S.detector.setParams(S.data.params);
      if (S.data.autostart && !S.autostarted && !S.running && !S.starting) { S.autostarted = true; start(); }
    },
    destroy() { stop(false); if (S.landmarker && S.landmarker.close) S.landmarker.close(); S.landmarker = null; },
  };
}

export default function (component) {
  const { parentElement, setStateValue, data } = component;
  const root = parentElement.querySelector('.ttw');
  if (!root) return;
  // Streamlit calls this function on every rerun with the same root, so keep one controller per root:
  // the camera and the hand model survive reruns instead of restarting on every tap.
  if (!root.__ttw) root.__ttw = createController(root);
  root.__ttw.apply(data, setStateValue);
  const controller = root.__ttw;
  // Streamlit may run a stale cleanup while the component is still mounted (rapid reruns),
  // so only release the camera once the component has really left the page.
  return () => setTimeout(() => {
    if (!root.isConnected && root.__ttw === controller) { controller.destroy(); root.__ttw = null; }
  }, 0);
}

"""Browser webcam piano: the camera runs in the learner's own browser, so it works online.

The desktop webcam window (table_piano.py) can only use the camera of the computer running
Streamlit, which on a hosted app is the server. This component instead runs camera capture,
MediaPipe hand tracking and tap detection inside the browser and sends only note names to
Python. Grading, coaching and storage stay in Python exactly as for on-screen key presses.
"""
import json
from pathlib import Path

import streamlit as st

from music import ALL_KEYS

ROOT = Path(__file__).resolve().parent
JS = (ROOT / 'webcam_component' / 'webcam_piano.mjs').read_text(encoding='utf-8')
HTML = '''<div class="ttw">
  <div class="ttw-bar">
    <button type="button" class="primary" data-act="start">📷 Start camera</button>
    <button type="button" data-act="cal">Calibrate corners</button>
    <button type="button" data-act="def">Default area</button>
    <button type="button" data-act="stop">Stop camera</button>
    <span class="ttw-status">Camera off</span>
  </div>
  <div class="ttw-stage"><video playsinline muted></video><canvas width="1280" height="720"></canvas></div>
  <div class="ttw-help">Place your hands over a table in view of the camera. The keys are drawn on the picture:
  tap a key firmly and lift your finger before the next note. Use <b>Calibrate corners</b> to fit the keys to a
  paper keyboard or table area (click top-left, top-right, bottom-right, bottom-left as you see them).
  Video never leaves this device; only the note names you play are sent to ToneTutor.</div>
</div>'''
CSS = '''
.ttw {color: var(--st-text-color); font-family: inherit;}
.ttw-bar {display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-bottom:8px;}
.ttw button {padding:6px 12px; border-radius:8px; border:1px solid #c9ccd3; background:#fff; color:#172336;
  cursor:pointer; font:inherit; font-size:14px;}
.ttw button.primary {background:#c0544f; border-color:#c0544f; color:#fff;}
.ttw button:disabled {opacity:.45; cursor:default;}
.ttw-status {font-size:13px; opacity:.85;}
.ttw-stage {position:relative; width:100%; max-width:880px; aspect-ratio:16/9; background:#151a24;
  border-radius:10px; overflow:hidden;}
.ttw-stage video {position:absolute; width:1px; height:1px; opacity:0; pointer-events:none;}
.ttw-stage canvas {display:block; width:100%; height:100%; cursor:crosshair;}
.ttw-help {font-size:12px; opacity:.75; margin-top:6px; max-width:880px; line-height:1.45;}
'''
WEBCAM = st.components.v2.component('tonetutor_browser_webcam', html=HTML, css=CSS, js=JS)

# Same thresholds as the desktop webcam window (table_piano.py).
SENSITIVITY = {
    'low': {'min_down_y': 9.0, 'min_depth_delta': 0.020, 'min_y_velocity': 120.0, 'min_z_velocity': 0.23},
    'normal': {'min_down_y': 6.0, 'min_depth_delta': 0.014, 'min_y_velocity': 90.0, 'min_z_velocity': 0.16},
    'high': {'min_down_y': 3.8, 'min_depth_delta': 0.008, 'min_y_velocity': 65.0, 'min_z_velocity': 0.10},
}


def parse_taps(raw):
    """Validate the component's tap state. Returns (nonce, [(id, note), ...]) or (None, [])."""
    if not isinstance(raw, str):
        return None, []
    try:
        obj = json.loads(raw)
    except ValueError:
        return None, []
    if not isinstance(obj, dict) or not isinstance(obj.get('nonce'), str) or not isinstance(obj.get('taps'), list):
        return None, []
    taps = [(t['id'], t['note']) for t in obj['taps'][-60:]
            if isinstance(t, dict) and type(t.get('id')) is int and t.get('note') in ALL_KEYS]
    return obj['nonce'][:40], taps


def take_new_taps(raw, cursor):
    """Notes tapped since `cursor` = (nonce, last_id). Returns (notes, new_cursor).

    The component keeps a rolling list of recent taps, so taps made during one rerun are
    never lost, and a new camera session (new nonce) starts counting from zero.
    """
    nonce, taps = parse_taps(raw)
    if nonce is None:
        return [], cursor
    last = cursor[1] if cursor and cursor[0] == nonce else 0
    notes = [note for tap_id, note in taps if tap_id > last]
    newest = max([last] + [tap_id for tap_id, _ in taps])
    return notes, (nonce, newest)


def browser_webcam_piano(key, target=None, sensitivity='normal', hide_labels=False):
    """Render the browser webcam piano and return the note names tapped since the last run."""
    result = WEBCAM(key=key,
                    data={'target': target or '', 'params': SENSITIVITY.get(sensitivity, SENSITIVITY['normal']),
                          'hideLabels': bool(hide_labels), 'autostart': bool(st.session_state.get('bw_autostart'))},
                    on_taps_change=lambda: None, on_status_change=lambda: None)
    status = getattr(result, 'status', None)
    if status == 'running':
        st.session_state.bw_autostart = True     # camera was allowed: reopen it automatically on other pages
    elif status == 'stopped':
        st.session_state.bw_autostart = False
    cursor_key = 'bw_cursor_' + key
    notes, st.session_state[cursor_key] = take_new_taps(getattr(result, 'taps', None),
                                                        st.session_state.get(cursor_key))
    return notes

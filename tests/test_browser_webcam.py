"""Tests for the browser webcam piano: tap hand-off to Python, and JS/Python logic parity.

The parity tests run the JavaScript module with Node (skipped when Node is not installed)
and check that its keyboard layout and tap detector match table_piano_core.py exactly.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from browser_webcam import SENSITIVITY, parse_taps, take_new_taps
from table_piano_core import FingerSmoother, KeyboardLayout, OneEuroFilter, TapDetector, note_at_sticky

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'webcam_component' / 'webcam_piano.mjs'


def tap_state(nonce, taps):
    return json.dumps({'nonce': nonce, 'taps': [{'id': i, 'note': n} for i, n in taps]})


class TapHandOffTests(unittest.TestCase):
    def test_new_taps_are_returned_once_in_order(self):
        notes, cursor = take_new_taps(tap_state('a1', [(1, 'C4'), (2, 'E4')]), None)
        self.assertEqual(notes, ['C4', 'E4'])
        notes, cursor = take_new_taps(tap_state('a1', [(1, 'C4'), (2, 'E4'), (3, 'G4')]), cursor)
        self.assertEqual(notes, ['G4'])
        notes, cursor = take_new_taps(tap_state('a1', [(1, 'C4'), (2, 'E4'), (3, 'G4')]), cursor)
        self.assertEqual(notes, [])
        self.assertEqual(cursor, ('a1', 3))

    def test_new_camera_session_restarts_counting(self):
        _, cursor = take_new_taps(tap_state('old', [(7, 'C4')]), None)
        notes, cursor = take_new_taps(tap_state('new', [(1, 'D4')]), cursor)
        self.assertEqual(notes, ['D4'])
        self.assertEqual(cursor, ('new', 1))

    def test_invalid_state_is_ignored(self):
        for raw in (None, '', 'not json', '[]', json.dumps({'nonce': 5, 'taps': []}),
                    json.dumps({'nonce': 'x', 'taps': 'C4'})):
            self.assertEqual(take_new_taps(raw, ('x', 2)), ([], ('x', 2)))
        nonce, taps = parse_taps(json.dumps({'nonce': 'n', 'taps': [
            {'id': 1, 'note': 'C4'}, {'id': '2', 'note': 'D4'}, {'id': 3, 'note': 'H9'}, {'id': True, 'note': 'E4'}]}))
        self.assertEqual((nonce, taps), ('n', [(1, 'C4')]))

    def test_normal_sensitivity_matches_reference_detector(self):
        reference = TapDetector()
        self.assertEqual(SENSITIVITY['normal'], {k: getattr(reference, k) for k in SENSITIVITY['normal']})
        self.assertEqual(set(SENSITIVITY), {'low', 'normal', 'high'})


def find_node():
    found = shutil.which('node')
    if found:
        return found
    bundled = ROOT / 'presentation_video' / 'tools_node22' / 'node-v22.23.5-win-x64' / 'node.exe'
    return str(bundled) if bundled.is_file() else None


NODE = find_node()

# A downstroke, settle, lift and second press on C4, then movement over another key.
SEQUENCE = [('L8', 'C4', 100, -0.10, 0.00), ('L8', 'C4', 109, -0.07, 0.04), ('L8', 'C4', 110, -0.069, 0.08),
            ('L8', 'C4', 110, -0.069, 0.25), ('L8', 'C4', 100, -0.10, 0.31), ('L8', 'C4', 109, -0.07, 0.36),
            ('L8', 'C4', 110, -0.069, 0.40), ('R12', 'E4', 200, -0.10, 0.50), ('R12', 'E4', 200, -0.07, 0.53),
            ('R12', 'E4', 200, -0.069, 0.56), ('R12', None, 240, -0.06, 0.60), ('R12', 'G4', 230, -0.10, 0.70),
            ('R12', 'G4', 237, -0.09, 0.73), ('R12', 'G4', 237.5, -0.09, 0.76)]
POINTS = [(x, y) for x in range(-10, 1011, 37) for y in (-5, 0, 50, 120, 287, 288, 300, 420, 479, 480, 481)]


@unittest.skipUnless(NODE, 'Node.js not available')
class JavaScriptParityTests(unittest.TestCase):
    def run_js(self, body):
        script = ("import { pathToFileURL } from 'node:url';\n"
                  f"const m = await import(pathToFileURL({json.dumps(str(MODULE))}).href);\n" + body)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'check.mjs'
            path.write_text(script, encoding='utf-8')
            out = subprocess.run([NODE, str(path)], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_keyboard_layout_matches_python(self):
        js = self.run_js(f"const L = m.buildLayout();\n"
                         f"console.log(JSON.stringify({json.dumps(POINTS)}.map(([x, y]) => m.noteAt(L, x, y))));")
        layout = KeyboardLayout()
        self.assertEqual(js, [layout.note_at(x, y) for x, y in POINTS])

    def test_tap_detector_matches_python_for_each_sensitivity(self):
        for name, params in SENSITIVITY.items():
            js = self.run_js(f"const d = m.makeTapDetector({json.dumps(params)});\n"
                             f"console.log(JSON.stringify({json.dumps(SEQUENCE)}.map("
                             f"([f, n, y, z, t]) => d.update(f, n, y, z, t))));")
            detector = TapDetector(**params)
            expected = [detector.update(f, n, y, z, t) for f, n, y, z, t in SEQUENCE]
            self.assertEqual(js, expected, name)
            if name == 'normal':   # the sequence must actually exercise taps, not only silence
                self.assertEqual([n for n in expected if n], ['C4', 'C4', 'E4'])

    def test_smoothing_and_sticky_keys_match_python(self):
        rng = __import__('random').Random(11)
        edge = 1000 / 14
        track = [(round(edge + rng.gauss(0, 6), 3), round(380 + rng.gauss(0, 30), 3), round(i / 30, 4))
                 for i in range(120)]
        track += [(round(edge + 40 + i, 3), 200.0, round((120 + i) / 30, 4)) for i in range(30)]
        js = self.run_js(
            f"const L = m.buildLayout(); const s = m.makeFingerSmoother(L);\n"
            f"const f = m.makeOneEuro();\n"
            f"const track = {json.dumps(track)};\n"
            "console.log(JSON.stringify({keys: track.map(([x, y, t]) => s.keyFor('R_8', x, y, t)),\n"
            "  filt: track.map(([x, y, t]) => f(x, t)),\n"
            "  sticky: track.map(([x, y]) => [m.noteAtSticky(L, x, y, 'C4'), m.noteAtSticky(L, x, y, 'D4'),"
            " m.noteAtSticky(L, x, y, null)])}));")
        layout = KeyboardLayout()
        smoother = FingerSmoother(layout)
        filt = OneEuroFilter()
        for i, (x, y, t) in enumerate(track):
            note, sx, sy = smoother.key_for('R_8', x, y, t)
            self.assertEqual(js['keys'][i][0], note, i)
            self.assertAlmostEqual(js['keys'][i][1], sx, places=9)
            self.assertAlmostEqual(js['keys'][i][2], sy, places=9)
            self.assertAlmostEqual(js['filt'][i], filt(x, t), places=9)
            self.assertEqual(js['sticky'][i], [note_at_sticky(layout, x, y, p) for p in ('C4', 'D4', None)], i)

    def test_homography_maps_corners_and_round_trips(self):
        js = self.run_js(
            "const src = [[100, 300], [1180, 330], [1240, 690], [40, 650]];\n"
            "const dst = [[0, 0], [1000, 0], [1000, 480], [0, 480]];\n"
            "const h = m.homography(src, dst), hi = m.homography(dst, src);\n"
            "const corners = src.map(([x, y]) => m.applyH(h, x, y));\n"
            "const back = m.applyH(hi, ...m.applyH(h, 640, 500));\n"
            "console.log(JSON.stringify({corners, back, area: m.polygonArea(src)}));")
        for (x, y), (u, v) in zip(js['corners'], [(0, 0), (1000, 0), (1000, 480), (0, 480)]):
            self.assertAlmostEqual(x, u, places=6)
            self.assertAlmostEqual(y, v, places=6)
        self.assertAlmostEqual(js['back'][0], 640, places=6)
        self.assertAlmostEqual(js['back'][1], 500, places=6)
        self.assertGreater(js['area'], 2000)


if __name__ == '__main__':
    unittest.main()

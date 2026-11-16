"""Headless tests for camera backend fallback and free-play webcam taps (no physical camera needed)."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

import database as db
from webcam_session import WEBCAM_MODES, camera_backends, frame_is_black, launch_webcam, open_camera


class FakeCapture:
    def __init__(self, frame, opened=True):
        self.frame, self.opened, self.released = frame, opened, False

    def isOpened(self):
        return self.opened

    def set(self, *_):
        return True

    def read(self):
        return True, self.frame

    def release(self):
        self.released = True


class FakeCV2:
    CAP_MSMF, CAP_DSHOW, CAP_ANY = 1400, 700, 0
    CAP_PROP_FRAME_WIDTH, CAP_PROP_FRAME_HEIGHT = 3, 4

    def __init__(self, by_backend):
        self.by_backend, self.calls = by_backend, []

    def VideoCapture(self, index, backend):
        self.calls.append((index, backend))
        return self.by_backend[backend]


BLACK = np.zeros((72, 128, 3), dtype=np.uint8)
LIVE = np.full((72, 128, 3), 120, dtype=np.uint8)


def ticking_clock(step=0.5):
    t = [0.0]

    def clock():
        t[0] += step
        return t[0]
    return clock


class CameraBackendTests(unittest.TestCase):
    def test_windows_prefers_media_foundation_then_directshow(self):
        names = [n for n, _ in camera_backends(FakeCV2({}), platform_name='nt')]
        self.assertEqual(names, ['Media Foundation', 'DirectShow'])
        self.assertEqual([n for n, _ in camera_backends(FakeCV2({}), platform_name='posix')], ['default'])

    def test_black_directshow_is_skipped_for_live_media_foundation(self):
        msmf, dshow = FakeCapture(LIVE), FakeCapture(BLACK)
        cv2 = FakeCV2({FakeCV2.CAP_MSMF: msmf, FakeCV2.CAP_DSHOW: dshow})
        cap, name, frame = open_camera(cv2, 1, platform_name='nt', clock=ticking_clock())
        self.assertIs(cap, msmf)
        self.assertEqual(name, 'Media Foundation')
        self.assertFalse(frame_is_black(frame))
        self.assertEqual(cv2.calls, [(1, FakeCV2.CAP_MSMF)])

    def test_falls_back_when_first_backend_stays_black(self):
        msmf, dshow = FakeCapture(BLACK), FakeCapture(LIVE)
        cv2 = FakeCV2({FakeCV2.CAP_MSMF: msmf, FakeCV2.CAP_DSHOW: dshow})
        cap, name, _ = open_camera(cv2, 0, platform_name='nt', warmup=1.0, clock=ticking_clock())
        self.assertIs(cap, dshow)
        self.assertEqual(name, 'DirectShow')
        self.assertTrue(msmf.released)

    def test_all_black_raises_a_readable_error(self):
        cv2 = FakeCV2({FakeCV2.CAP_MSMF: FakeCapture(BLACK), FakeCV2.CAP_DSHOW: FakeCapture(None, opened=False)})
        with self.assertRaises(RuntimeError) as ctx:
            open_camera(cv2, 0, platform_name='nt', warmup=1.0, clock=ticking_clock())
        message = str(ctx.exception)
        self.assertIn('Media Foundation: black picture', message)
        self.assertIn('DirectShow: not available', message)
        self.assertIn('another device number', message)

    def test_busy_camera_reports_no_frames_without_spinning(self):
        class BusyCapture(FakeCapture):
            def read(self):
                return False, None
        sleeps = []
        cv2 = FakeCV2({FakeCV2.CAP_MSMF: BusyCapture(None), FakeCV2.CAP_DSHOW: BusyCapture(None)})
        with self.assertRaises(RuntimeError) as ctx:
            open_camera(cv2, 0, platform_name='nt', warmup=1.0, clock=ticking_clock(), sleep=sleeps.append)
        self.assertIn('no frames, camera may be in use', str(ctx.exception))
        self.assertTrue(sleeps and all(s > 0 for s in sleeps))

    def test_free_mode_is_a_valid_launch_mode(self):
        self.assertIn('free', WEBCAM_MODES)
        with patch('webcam_session.webcam_requirements', return_value=[]), \
             patch('webcam_session.subprocess.Popen') as popen:
            session = launch_webcam('DEMO-001', mode='free', camera=1)
        command = popen.call_args[0][0]
        self.assertEqual(command[command.index('--mode') + 1], 'free')
        self.assertEqual(command[command.index('--camera') + 1], '1')
        self.assertEqual(session.mode, 'free')


class WebcamTapTests(unittest.TestCase):
    def test_taps_are_ordered_scoped_and_cursor_based(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(db, 'DB', Path(temp) / 'test.db'):
                db.initialize()
                self.assertEqual(db.latest_webcam_tap_id('A-1'), 0)
                first = db.record_webcam_tap('A-1', 'C4')
                db.record_webcam_tap('B-2', 'G4')
                db.record_webcam_tap('A-1', 'E4')
                self.assertEqual([t['note'] for t in db.webcam_taps_since('A-1')], ['C4', 'E4'])
                self.assertEqual([t['note'] for t in db.webcam_taps_since('A-1', first)], ['E4'])
                self.assertEqual([t['note'] for t in db.webcam_taps_since('B-2')], ['G4'])
                self.assertEqual(db.latest_webcam_tap_id('A-1'), first + 2)

    def test_invalid_notes_and_learner_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(db, 'DB', Path(temp) / 'test.db'):
                db.initialize()
                with self.assertRaises(ValueError):
                    db.record_webcam_tap('A-1', 'H9')
                with self.assertRaises(ValueError):
                    db.record_webcam_tap('A; DROP', 'C4')

    def test_old_taps_are_pruned_per_learner(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(db, 'DB', Path(temp) / 'test.db'), patch.object(db, 'WEBCAM_TAP_KEEP', 5):
                db.initialize()
                for _ in range(8):
                    db.record_webcam_tap('A-1', 'D4')
                db.record_webcam_tap('B-2', 'F4')
                self.assertEqual(len(db.webcam_taps_since('A-1', limit=100)), 5)
                self.assertEqual(len(db.webcam_taps_since('B-2', limit=100)), 1)


if __name__ == '__main__':
    unittest.main()

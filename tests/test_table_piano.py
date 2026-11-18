"""Headless tests: don't require a physical webcam, MediaPipe or Pygame."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import database as db
from piano_coach import DRILLS, get_context, next_piano_mission
from table_piano_core import KeyboardLayout, TapDetector


class TablePianoTests(unittest.TestCase):
    def test_black_keys_take_precedence(self):
        layout = KeyboardLayout(width=700, height=480, octaves=1)
        self.assertEqual(layout.note_at(20, 250), 'C4')
        self.assertEqual(layout.note_at(100, 100), 'C#4')
        self.assertEqual(layout.note_at(100, 420), 'D4')
        self.assertIsNone(layout.note_at(-1, 150))
        self.assertIsNone(layout.note_at(450, 481))

    def test_two_octaves_support_existing_coach_missions(self):
        layout = KeyboardLayout(width=980, height=480, octaves=2)
        self.assertEqual(layout.note_at(7*70 + 10, 460), 'C5')
        self.assertEqual(layout.note_at(13*70 + 10, 460), 'B5')
        self.assertEqual(len(layout.whites), 14)
        self.assertEqual(len(layout.blacks), 10)
        for drill in DRILLS.values():
            supported = {n for n, _ in layout.whites + layout.blacks}
            self.assertTrue(all(note in supported for note in drill['notes']))

    def test_tap_needs_downstroke_settle_and_rearm(self):
        detector = TapDetector()
        finger = ('Left', 8)
        self.assertIsNone(detector.update(finger, 'C4', 100, -.1, 0.00))
        self.assertIsNone(detector.update(finger, 'C4', 109, -.07, 0.04))
        self.assertEqual(detector.update(finger, 'C4', 110, -.069, 0.08), 'C4')
        self.assertIsNone(detector.update(finger, 'C4', 110, -.069, 0.25))
        self.assertIsNone(detector.update(finger, 'C4', 100, -.10, 0.31))
        self.assertIsNone(detector.update(finger, 'C4', 109, -.07, 0.36))
        self.assertEqual(detector.update(finger, 'C4', 110, -.069, 0.40), 'C4')

    def test_hovering_and_exiting_key_do_not_trigger(self):
        detector = TapDetector()
        fid = ('Right', 12)
        for index in range(10):
            self.assertIsNone(detector.update(fid, 'D4', 120.0 + index*.1, -.055, index*.04))
        self.assertIsNone(detector.update(fid, None, 125, -.055, .5))

    def test_webcam_mission_is_recorded_and_informs_next_mission(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(db, 'DB', Path(temp)/'test.db'):
                db.initialize()
                db.ensure_learner('CAMERA-1')
                db.ensure_learner('CAMERA-2')
                mission = db.start_coach_mission('CAMERA-1', 'middle_c', ['C4','D4','C4'], 'Test webcam inputs')
                with self.assertRaisesRegex(ValueError, 'Unknown'):
                    db.complete_coach_mission('CAMERA-2', mission['id'], ['C4','D4','C4'])
                result = db.complete_coach_mission('CAMERA-1', mission['id'], ['G4','C4','D4','C4'],
                                                   input_source='browser_webcam')
                self.assertEqual((result['mistakes'], result['accuracy']), (1, .75))
                self.assertIsNone(db.coach_active('CAMERA-1'))
                history = db.coach_history('CAMERA-1')
                self.assertEqual(history[0]['input_source'], 'browser_webcam')
                self.assertEqual(history[0]['mistakes'], 1)
                self.assertIn('piano_history', get_context('CAMERA-1'))
                self.assertEqual(next_piano_mission('CAMERA-1','rules')['mode'],'rules')

    def test_invalid_mission_results_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(db, 'DB', Path(temp)/'test.db'):
                db.initialize()
                db.ensure_learner('CAMERA-1')
                mission = db.start_coach_mission('CAMERA-1', 'middle_c', ['C4','D4'], 'Test')
                with self.assertRaisesRegex(ValueError, 'Invalid input source'):
                    db.complete_coach_mission('CAMERA-1', mission['id'], ['C4','D4'], input_source='mediapipe_webcam')
                with self.assertRaisesRegex(ValueError, 'Invalid piano note trace'):
                    db.complete_coach_mission('CAMERA-1', mission['id'], ['C10'])
                with self.assertRaisesRegex(ValueError, 'Finish all required notes'):
                    db.complete_coach_mission('CAMERA-1', mission['id'], ['C4'])


if __name__ == '__main__':
    unittest.main()

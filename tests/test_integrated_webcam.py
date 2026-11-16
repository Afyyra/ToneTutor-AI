"""No webcam, real Gemini key, or new optional dependencies required."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import database as db
from webcam_session import webcam_requirements, launch_webcam, stop_webcam


class IntegratedWebcamTests(unittest.TestCase):
    def test_one_click_launcher_uses_selected_interpreter_and_learner(self):
        with tempfile.TemporaryDirectory() as path:
            root = Path(path)
            (root / 'hand_landmarker.task').write_bytes(b'mock task for launcher test')
            (root / 'table_piano.py').write_text('# test')
            fake_process = MagicMock()
            fake_process.poll.return_value = None
            with patch('webcam_session.importlib.util.find_spec', return_value=object()), \
                 patch('webcam_session.subprocess.Popen', return_value=fake_process) as popen:
                session = launch_webcam('DEMO-001', mode='coach', controller='gemini',
                                        camera=1, sensitivity='high', root=root)
                command = popen.call_args.args[0]
                self.assertEqual(command[0], __import__('sys').executable)
                self.assertIn('DEMO-001', command)
                self.assertIn('gemini', command)
                self.assertIn('high', command)
                self.assertNotIn('shell', popen.call_args.kwargs)
                stop_webcam(session)
                self.assertTrue(session.stop_file.is_file())
                session.stop_file.unlink(missing_ok=True)
                session.log_file.unlink(missing_ok=True)

    def test_launcher_rejects_unsafe_options(self):
        with self.assertRaises(ValueError):
            launch_webcam('A; echo hello')
        with self.assertRaises(ValueError):
            launch_webcam('DEMO-001', mode='bash')
        with self.assertRaises(ValueError):
            launch_webcam('DEMO-001', camera=99)

    def test_missing_model_is_reported_before_camera_start(self):
        with tempfile.TemporaryDirectory() as path:
            root = Path(path)
            (root / 'table_piano.py').write_text('# test')
            with patch('webcam_session.importlib.util.find_spec', return_value=object()):
                self.assertTrue(any('hand_landmarker.task' in e for e in webcam_requirements(root)))

    def test_webcam_jam_feedback_is_learner_scoped(self):
        with tempfile.TemporaryDirectory() as path:
            with patch.object(db, 'DB', Path(path) / 'test.sqlite'):
                db.initialize()
                db.ensure_learner('P1')
                db.ensure_learner('P2')
                self.assertIsNone(db.latest_webcam_jam_feedback('P1'))
                db.save_webcam_jam_feedback('P1',{
                    'title':'Play a descending response',
                    'prompt':'Try a 3-note descending answer to your melody.',
                    'reason':'Your original phrase climbed.',
                    'mode':'rules'})
                self.assertIsNone(db.latest_webcam_jam_feedback('P2'))
                self.assertIn('descending',db.latest_webcam_jam_feedback('P1')['prompt'])
                with self.assertRaises(ValueError):
                    db.save_webcam_jam_feedback('P1',{'prompt':'missing title'})


if __name__ == '__main__':
    unittest.main()

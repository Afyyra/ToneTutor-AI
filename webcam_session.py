"""Launch/stop the optional local webcam piano from the same Piano Coach UI.

No video or hand landmarks are sent to Gemini. Webcam capture occurs in a
separate local OpenCV process; the two UIs share only learner-scoped SQLite
practice records. This is intended for the SAME laptop running Streamlit.
"""
from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parent
MODEL_URL = ('https://storage.googleapis.com/mediapipe-models/hand_landmarker/'
             'hand_landmarker/float16/1/hand_landmarker.task')
WEBCAM_MODES = ('coach', 'jam', 'free')
BLACK_LEVEL = 2.0  # mean pixel value (0-255) below which a frame counts as black


def camera_backends(cv2, platform_name=None):
    """Capture backends to try, most reliable first.

    On some Windows laptops DirectShow opens the camera but only ever returns
    black frames, while Media Foundation delivers the live picture, so Media
    Foundation is tried first and DirectShow is kept as a fallback.
    """
    if (platform_name or os.name) == 'nt':
        return [('Media Foundation', cv2.CAP_MSMF), ('DirectShow', cv2.CAP_DSHOW)]
    return [('default', cv2.CAP_ANY)]


def frame_is_black(frame) -> bool:
    return frame is None or float(frame[::8, ::8].mean()) < BLACK_LEVEL


def open_camera(cv2, index, width=1280, height=720, warmup=3.0, platform_name=None,
                clock=time.monotonic, sleep=time.sleep):
    """Open camera `index` with the first backend that delivers a real picture.

    Returns (capture, backend_name, first_frame). Raises RuntimeError with a
    learner-readable explanation when every backend fails, stays black, or
    delivers no frames (typically because another program is using the camera).
    """
    tried = []
    for name, backend in camera_backends(cv2, platform_name):
        cap = cv2.VideoCapture(index, backend)
        if not cap.isOpened():
            cap.release()
            tried.append(name + ': not available')
            continue
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        got_frame = False
        start = clock()
        while clock() - start < warmup:
            ok, frame = cap.read()
            if ok and frame is not None:
                got_frame = True
                if not frame_is_black(frame):
                    return cap, name, frame
            else:
                sleep(0.05)  # a busy camera fails instantly; do not spin
        cap.release()
        tried.append(name + (': black picture' if got_frame else ': no frames, camera may be in use'))
    raise RuntimeError(f'Camera {index} gave no picture ({"; ".join(tried)}). Close other apps or ToneTutor '
                       'camera windows using this camera, open any privacy shutter, check Windows camera '
                       'permission, or choose another device number.')


def preview_frame(index):
    """One mirrored RGB still from camera `index`, so learners can tell devices apart.

    The frame is returned to the local Streamlit page only; it is never saved or sent anywhere.
    """
    import cv2
    cap, backend, frame = open_camera(cv2, index, warmup=4.0)
    try:
        ok, latest = cap.read()
        if ok and not frame_is_black(latest):
            frame = latest
    finally:
        cap.release()
    return cv2.cvtColor(cv2.flip(frame, 1), cv2.COLOR_BGR2RGB), backend


@dataclass
class WebcamSession:
    process: subprocess.Popen
    learner: str
    mode: str
    controller: str
    stop_file: Path
    log_file: Path

    def is_running(self) -> bool:
        return self.process.poll() is None

    def recent_log(self, max_lines=10) -> str:
        try:
            lines = self.log_file.read_text(encoding='utf-8', errors='replace').splitlines()
            return '\n'.join(lines[-max_lines:])
        except OSError:
            return ''


def webcam_requirements(root: Path = ROOT):
    """Return user-facing setup issues without importing optional heavy packages."""
    root = Path(root)
    issues = []
    if not (root / 'hand_landmarker.task').is_file():
        issues.append('Missing hand_landmarker.task (download the MediaPipe hand model).')
    missing = [label for module, label in [('mediapipe', 'mediapipe'),
                                             ('cv2', 'opencv-python'),
                                             ('pygame', 'pygame')]
               if importlib.util.find_spec(module) is None]
    if missing:
        issues.append('Missing Python packages in the running interpreter: ' + ', '.join(missing) + '.')
    if sys.version_info >= (3, 15) and missing:
        issues.append('Python 3.15 may lack Pygame wheels. Use a separate Python 3.12 environment for webcam mode.')
    if not (root / 'table_piano.py').is_file():
        issues.append('Missing table_piano.py webcam companion.')
    return issues


def launch_webcam(learner, mode='coach', controller='rules', camera=0,
                  sensitivity='normal', root: Path = ROOT) -> WebcamSession:
    if not isinstance(learner, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,48}', learner):
        raise ValueError('Invalid anonymous learner ID')
    if mode not in WEBCAM_MODES:
        raise ValueError('Invalid webcam mode')
    if controller not in ('rules', 'gemini'):
        raise ValueError('Invalid tutor controller')
    if type(camera) is not int or camera not in (0, 1, 2, 3):
        raise ValueError('Camera index must be 0, 1, 2 or 3')
    if sensitivity not in ('low', 'normal', 'high'):
        raise ValueError('Invalid camera tap sensitivity')
    issues = webcam_requirements(root)
    if issues:
        raise RuntimeError('\n'.join(issues))
    # No shell=True and no executable from user input. This uses the exact
    # interpreter used to run Streamlit, avoiding Python 3.15/3.12 confusion.
    identifier = uuid.uuid4().hex
    stop_file = Path(tempfile.gettempdir()) / f'tonetutor_camera_stop_{identifier}.flag'
    log_file = Path(tempfile.gettempdir()) / f'tonetutor_camera_{identifier}.log'
    command = [sys.executable, '-u', str(Path(root) / 'table_piano.py'),
               '--learner', learner, '--mode', mode,
               '--controller', controller,
               '--camera', str(camera), '--sensitivity', sensitivity,
               '--stop-file', str(stop_file)]
    with log_file.open('w', encoding='utf-8') as log:
        process = subprocess.Popen(command, cwd=str(root),
                                   stdout=log, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL)
    return WebcamSession(process, learner, mode, controller, stop_file, log_file)


def stop_webcam(session: WebcamSession, force=False):
    """Request graceful camera-window closure, then force-stop only if needed."""
    if session is None or not session.is_running():
        return
    if force:
        session.process.terminate()
        return
    session.stop_file.touch()

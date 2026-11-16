"""Pure geometry and conservative gesture state for an optional webcam table piano.

MediaPipe's single RGB camera cannot recover a measured fingertip-to-table distance.
We therefore use a heuristic approach/deceleration gesture, plus a release requirement,
NOT a claim of reliable physical contact sensing.
"""
from dataclasses import dataclass
from typing import Optional

WHITE_CLASSES = ('C', 'D', 'E', 'F', 'G', 'A', 'B')
BLACK_AFTER = {0: 'C#', 1: 'D#', 3: 'F#', 4: 'G#', 5: 'A#'}
FINGERTIPS = (4, 8, 12, 16, 20)
TIP_TO_MCP = {4: 2, 8: 5, 12: 9, 16: 13, 20: 17}


class KeyboardLayout:
    """Two octaves C4–B5, compatible with ToneTutor's approved coach missions.

    Coordinates are on a rectified 1000x480 desk / paper surface.
    """
    def __init__(self, width=1000, height=480, octaves=2):
        if octaves not in (1, 2):
            raise ValueError('Only one or two octaves supported')
        if width < 280 or height < 180:
            raise ValueError('Keyboard area is too small')
        self.width, self.height, self.octaves = width, height, octaves
        self.whites = []
        self.blacks = []
        n = 7 * octaves
        unit = width / n
        for octave in range(4, 4 + octaves):
            for offset, name in enumerate(WHITE_CLASSES):
                i = (octave - 4) * 7 + offset
                x1, x2 = i * unit, (i + 1) * unit
                self.whites.append((f'{name}{octave}', (x1, 0, x2, height)))
                if offset in BLACK_AFTER:
                    cx = x2
                    bw = unit * 0.59
                    self.blacks.append((f'{BLACK_AFTER[offset]}{octave}',
                                        (cx - bw / 2, 0, cx + bw / 2, height * 0.60)))

    def note_at(self, x, y):
        if not (0 <= x <= self.width and 0 <= y <= self.height):
            return None
        for note, (x1, y1, x2, y2) in self.blacks + self.whites:
            if x1 <= x < x2 and y1 <= y < y2:
                return note
        return None


@dataclass
class FingerState:
    y: float
    z: float
    t: float
    armed: bool = True
    pending_note: Optional[str] = None
    pending_since: float = 0.0
    last_note: Optional[str] = None
    last_trigger: float = -1e9
    lifts: int = 0


class TapDetector:
    """One press per downstroke, never a held-finger repeat.

    Relative depth is (fingertip.z - base_knuckle.z). Positive change *may*
    indicate the fingertip moved away from the camera on a top-down mount.
    Image y movement is useful mainly on an oblique camera. Both are heuristics.
    """
    def __init__(self, min_down_y=6.0, min_depth_delta=0.014,
                 min_y_velocity=90.0, min_z_velocity=0.16,
                 release_y=5.0, release_z=0.010, settle_y=3.0,
                 cooldown=0.20, settle_window=0.17):
        self.min_down_y = min_down_y
        self.min_depth_delta = min_depth_delta
        self.min_y_velocity = min_y_velocity
        self.min_z_velocity = min_z_velocity
        self.release_y = release_y
        self.release_z = release_z
        self.settle_y = settle_y
        self.cooldown = cooldown
        self.settle_window = settle_window
        self.states = {}

    def forget_missing(self, visible_keys):
        """A lost landmark must not continue a pending gesture or stay locked forever."""
        for key in list(self.states):
            if key not in visible_keys:
                del self.states[key]

    def update(self, finger_id, note, y, relative_z, now):
        """Return a note only after a downstroke followed by deceleration.

        A finger must lift, leave the keyboard, or disappear from tracking to
        rearm. This intentionally favours avoiding spurious notes over speed.
        """
        if finger_id not in self.states:
            self.states[finger_id] = FingerState(y, relative_z, now)
            return None
        s = self.states[finger_id]
        dy, dz = y - s.y, relative_z - s.z
        dt = max(now - s.t, 0.001)
        s.y, s.z, s.t = y, relative_z, now
        if note is None:
            s.armed = True
            s.pending_note = None
            s.lifts = 0
            return None
        if s.pending_note and (s.pending_note != note or now - s.pending_since > self.settle_window):
            s.pending_note = None
        lifted = dy <= -self.release_y or dz <= -self.release_z
        if not s.armed:
            if lifted:
                s.lifts += 1
                if s.lifts >= 1 and now - s.last_trigger >= self.cooldown:
                    s.armed = True
                    s.lifts = 0
            else:
                s.lifts = 0
            return None
        if now - s.last_trigger < self.cooldown:
            return None
        downward = ((dy >= self.min_down_y and dy / dt >= self.min_y_velocity)
                    or (dz >= self.min_depth_delta and dz / dt >= self.min_z_velocity))
        if s.pending_note is None:
            if downward and dt < 0.25:
                s.pending_note = note
                s.pending_since = now
            return None
        # Require the fingertip to remain over the same key while slowing.
        if abs(dy) <= self.settle_y and abs(dz) <= self.min_depth_delta * 0.8:
            s.pending_note = None
            s.armed = False
            s.last_note = note
            s.last_trigger = now
            return note
        return None

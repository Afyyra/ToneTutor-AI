"""Precision of fingertip aiming: jitter smoothing and sticky key borders (table_piano_core)."""
import random
import statistics
import unittest

from table_piano_core import FingerSmoother, KeyboardLayout, OneEuroFilter, note_at_sticky

FPS = 30.0


def frames(n):
    return [i / FPS for i in range(n)]


class OneEuroTests(unittest.TestCase):
    def test_still_finger_jitter_is_strongly_reduced(self):
        rng = random.Random(4)
        f = OneEuroFilter()
        raw = [500 + rng.gauss(0, 4) for _ in range(300)]          # camera noise, layout units
        smooth = [f(x, t) for x, t in zip(raw, frames(300))]
        self.assertLess(statistics.pstdev(smooth[30:]), statistics.pstdev(raw[30:]) * 0.45)

    def test_real_movement_is_followed_quickly(self):
        f = OneEuroFilter()
        ts = frames(60)
        out = [f(100.0 if i < 20 else 200.0, t) for i, t in enumerate(ts)]   # finger jumps one key and a half
        self.assertLess(abs(out[19] - 100), 1e-9)
        settled = next(i for i, v in enumerate(out) if i >= 20 and abs(v - 200) < 5)
        self.assertLessEqual((settled - 20) / FPS, 0.35)   # within about a third of a second

    def test_constant_input_is_unchanged_and_bad_timestamps_are_safe(self):
        f = OneEuroFilter()
        self.assertEqual([f(42.0, t) for t in (0.0, 0.0, -1.0, 0.1)], [42.0, 42.0, 42.0, 42.0])


class StickyKeyTests(unittest.TestCase):
    def setUp(self):
        self.layout = KeyboardLayout()      # white keys are 1000/14 = 71.4 units wide
        self.edge = 1000 / 14               # border between C4 and D4 below the black keys

    def test_border_hover_keeps_the_current_key(self):
        note = 'C4'
        for dx in (2, -1, 3, 5, -2, 6):     # wobbling up to 6 units past the border
            note = note_at_sticky(self.layout, self.edge + dx, 400, note)
            self.assertEqual(note, 'C4')

    def test_clear_move_changes_key(self):
        self.assertEqual(note_at_sticky(self.layout, self.edge + 8, 400, 'C4'), 'D4')
        self.assertEqual(note_at_sticky(self.layout, self.edge + 30, 400, 'C4'), 'D4')

    def test_black_key_entered_from_white_key(self):
        # Just inside the black key's lower edge stays on the white key; well inside switches.
        self.assertEqual(note_at_sticky(self.layout, self.edge, 288 - 3, 'C4'), 'C4')
        self.assertEqual(note_at_sticky(self.layout, self.edge, 200, 'C4'), 'C#4')

    def test_no_previous_key_or_leaving_keyboard(self):
        self.assertEqual(note_at_sticky(self.layout, 30, 400, None), 'C4')
        self.assertEqual(note_at_sticky(self.layout, -3, 400, 'C4'), 'C4')       # within margin of the edge
        self.assertIsNone(note_at_sticky(self.layout, -20, 400, 'C4'))


class FingerSmootherTests(unittest.TestCase):
    def test_noisy_hover_on_a_border_does_not_flicker(self):
        layout = KeyboardLayout()
        edge = 1000 / 14
        rng = random.Random(7)
        raw_keys, smooth_keys = [], []
        smoother = FingerSmoother(layout)
        for t in frames(200):
            x, y = edge + 2 + rng.gauss(0, 4), 400 + rng.gauss(0, 4)
            raw_keys.append(layout.note_at(x, y))
            smooth_keys.append(smoother.key_for('R_8', x, y, t)[0])
        changes = lambda seq: sum(a != b for a, b in zip(seq, seq[1:]))
        self.assertGreater(changes(raw_keys), 40)          # raw position flips between C4 and D4
        self.assertLessEqual(changes(smooth_keys), 2)      # smoothed, sticky key barely changes

    def test_forgets_fingers_that_disappear(self):
        smoother = FingerSmoother(KeyboardLayout())
        smoother.key_for('a', 10, 400, 0.0)
        smoother.key_for('b', 90, 400, 0.0)
        smoother.forget_missing({'a'})
        self.assertEqual(list(smoother.fingers), ['a'])


if __name__ == '__main__':
    unittest.main()

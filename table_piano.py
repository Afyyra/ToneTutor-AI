"""Local MediaPipe Table Piano companion for ToneTutor AI.

Can be launched from the Streamlit Piano Coach UI. Uses the SAME SQLite DB.
Cameras do not reliably work through a remote hosted Streamlit server.
No images or video are saved; only note presses / existing learner history.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import time

from table_piano_core import FINGERTIPS, TIP_TO_MCP, FingerSmoother, KeyboardLayout, TapDetector
from webcam_session import frame_is_black, open_camera

MODEL_URL = ('https://storage.googleapis.com/mediapipe-models/hand_landmarker/'
             'hand_landmarker/float16/1/hand_landmarker.task')


def build_audio():
    import numpy as np
    import pygame
    from music import ALL_KEYS, frequency
    try:
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=256)
        pygame.mixer.set_num_channels(16)
    except pygame.error as exc:
        raise RuntimeError(f'Audio output unavailable: {exc}') from exc
    rate = 44100
    samples = np.arange(int(rate * 0.60), dtype=np.float64) / rate
    envelope = np.exp(-5.2 * samples)
    sounds = {}
    for note in ALL_KEYS:
        f = frequency(note)
        wave = (0.58 * np.sin(2 * np.pi * f * samples)
                + 0.20 * np.sin(4 * np.pi * f * samples)
                + 0.07 * np.sin(6 * np.pi * f * samples)) * envelope
        mono = (np.clip(wave, -1, 1) * 25000).astype(np.int16)
        stereo = np.column_stack((mono, mono))
        sounds[note] = pygame.sndarray.make_sound(stereo)
    return pygame, sounds


def draw_keyboard(cv2, image, layout, origin, dimensions, highlighted=None, target=None):
    """Draw keyboard over a view; black keys take visual precedence."""
    x0, y0 = origin
    dw, dh = dimensions
    sx, sy = dw / layout.width, dh / layout.height
    layer = image.copy()
    for note, (x1, y1, x2, y2) in layout.whites:
        p1 = (round(x0 + x1 * sx), round(y0 + y1 * sy))
        p2 = (round(x0 + x2 * sx), round(y0 + y2 * sy))
        bg = (105, 238, 155) if note == highlighted else (120, 197, 252) if note == target else (235, 235, 235)
        cv2.rectangle(layer, p1, p2, bg, -1)
        cv2.rectangle(layer, p1, p2, (35, 35, 35), 1)
        cv2.putText(layer, note, (p1[0] + 3, p2[1] - 11), cv2.FONT_HERSHEY_SIMPLEX,
                    0.39, (20, 20, 20), 1, cv2.LINE_AA)
    for note, (x1, y1, x2, y2) in layout.blacks:
        p1 = (round(x0 + x1 * sx), round(y0 + y1 * sy))
        p2 = (round(x0 + x2 * sx), round(y0 + y2 * sy))
        bg = (65, 205, 115) if note == highlighted else (140, 145, 245) if note == target else (20, 25, 37)
        cv2.rectangle(layer, p1, p2, bg, -1)
        cv2.putText(layer, note, (p1[0] + 2, p2[1] - 9), cv2.FONT_HERSHEY_SIMPLEX,
                    0.27, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.addWeighted(layer, 0.62, image, 0.38, 0, image)


def put_lines(cv2, frame, lines):
    h, w = frame.shape[:2]
    strip = min(h, 35 + 25 * len(lines))
    cv2.rectangle(frame, (0, 0), (w, strip), (15, 25, 39), -1)
    for i, line in enumerate(lines):
        cv2.putText(frame, str(line)[:105], (12, 26 + 25 * i),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, (246, 246, 246), 1, cv2.LINE_AA)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Local webcam-based ToneTutor table piano')
    parser.add_argument('--learner', default='DEMO-001', help='Same anonymous learner ID used in Streamlit')
    parser.add_argument('--mode', choices=['coach', 'jam', 'free'], default='coach')
    parser.add_argument('--controller', choices=['rules', 'gemini'], default='rules', help='Used for Creative Jam follow-ups only')
    parser.add_argument('--camera', type=int, default=0)
    parser.add_argument('--model', default=str(Path(__file__).with_name('hand_landmarker.task')))
    parser.add_argument('--stop-file', default=None, help='Optional app-issued graceful shutdown flag')
    parser.add_argument('--octaves', type=int, choices=[1, 2], default=2,
                        help='Two octaves required for some AI Piano Coach missions')
    parser.add_argument('--no-mirror', action='store_true')
    parser.add_argument('--sensitivity', choices=['low','normal','high'], default='normal',
                        help='High is easier to trigger but may create more false notes')
    args = parser.parse_args(argv)

    if not Path(args.model).is_file():
        parser.error(f'MediaPipe model missing: {args.model}\n'
                     f'Download once to hand_landmarker.task:\n{MODEL_URL}\n'
                     'PowerShell: Invoke-WebRequest -Uri "' + MODEL_URL + '" -OutFile hand_landmarker.task')

    try:
        import cv2
        import numpy as np
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision
    except ImportError as exc:
        parser.error('Install optional dependencies first: python -m pip install -r requirements-webcam.txt; ' + str(exc))

    import database as db
    from piano_coach import respond_to_jam
    from dotenv import load_dotenv
    load_dotenv()
    db.initialize()
    db.ensure_learner(args.learner)
    pygame, sounds = build_audio()

    try:
        cap, backend_name, _ = open_camera(cv2, args.camera)
    except RuntimeError:
        pygame.quit()
        raise
    print(f'Camera {args.camera} opened with {backend_name}.', flush=True)

    # Click corners on the INITIAL camera view, in this precise order:
    # top-left, top-right, bottom-right, bottom-left of the flat playing area.
    corners = []
    homography = None
    layout = KeyboardLayout(octaves=args.octaves)
    smoother = FingerSmoother(layout)  # steadier aiming and sticky key borders
    detector = TapDetector(
        min_down_y={'low':9.0, 'normal':6.0, 'high':3.8}[args.sensitivity],
        min_depth_delta={'low':0.020, 'normal':0.014, 'high':0.008}[args.sensitivity],
        min_y_velocity={'low':120., 'normal':90., 'high':65.}[args.sensitivity],
        min_z_velocity={'low':0.23, 'normal':0.16, 'high':0.10}[args.sensitivity])
    window = 'ToneTutor - Webcam Table Piano (Local DEMO)'
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window, 1100, 660)
    state = {'frame': None, 'note': '', 'note_until': 0.0, 'message': f'Camera {args.camera} via {backend_name}.',
             'black_since': None,
             'jam_notes': [], 'last_mission_id': None, 'last_check': 0.,
             'mission': None, 'progress': None}

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and homography is None and len(corners) < 4:
            corners.append((float(x), float(y)))

    cv2.setMouseCallback(window, on_mouse)
    options = vision.HandLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(args.model)),
        running_mode=vision.RunningMode.VIDEO,
        num_hands=2, min_hand_detection_confidence=0.60,
        min_hand_presence_confidence=0.55, min_tracking_confidence=0.60)

    begin = time.monotonic()
    last_timestamp = -1
    print('ToneTutor local webcam piano: Q quit | C recalibrate | J submit Jam phrase')
    print('Click 4 table corners TL, TR, BR, BL. Audio and hand analysis remain local.')
    print('Camera tap detection is heuristic. For reliability use a slanted camera angle, matte surface and good lighting.')
    try:
        with vision.HandLandmarker.create_from_options(options) as landmarker:
            while cap.isOpened():
                if args.stop_file and Path(args.stop_file).exists():
                    print('Stop requested by ToneTutor UI.', flush=True)
                    break
                success, raw = cap.read()
                if not success:
                    print('Camera frame unavailable; exiting.')
                    break
                frame = cv2.flip(raw, 1) if not args.no_mirror else raw
                h, w = frame.shape[:2]
                now = time.monotonic()
                # A camera that turns black mid-session (shutter, another app) should be explained, not silent.
                if frame_is_black(frame):
                    state['black_since'] = state['black_since'] or now
                    if now - state['black_since'] > 2.0:
                        state['message'] = ('Camera picture is black: open the privacy shutter, close other '
                                            'camera apps, or restart with another device number.')
                elif state['black_since'] is not None:
                    state['black_since'] = None
                    state['message'] = 'Camera picture restored.'
                if len(corners) == 4 and homography is None:
                    target = np.float32([[0, 0], [layout.width, 0],
                                         [layout.width, layout.height], [0, layout.height]])
                    src = np.float32(corners)
                    area = abs(cv2.contourArea(src))
                    if area < 2000:
                        corners.clear()
                        state['message'] = 'Invalid corners: choose a larger region.'
                    else:
                        homography = cv2.getPerspectiveTransform(src, target)
                        detector.states.clear()
                        smoother.fingers.clear()
                        state['message'] = 'Calibrated desk area. Press C to recalibrate.'

                if homography is not None:
                    view = cv2.warpPerspective(frame, homography, (layout.width, layout.height))
                    box = (0, 0, layout.width, layout.height)
                else:
                    view = frame.copy()
                    box = (int(w * .045), int(h * .49), int(w * .91), int(h * .45))
                bx, by, bw, bh = box

                mission = None
                if args.mode == 'coach' and now - state['last_check'] > .40:
                    state['mission'] = db.coach_active(args.learner)
                    if state['mission']:
                        state['progress'] = db.table_piano_progress(args.learner, state['mission']['id'])
                    state['last_check'] = now
                mission = state['mission'] if args.mode == 'coach' else None
                progress = state['progress'] if mission else None
                count = progress['correct_notes'] if progress else 0
                target_note = mission['notes'][count] if mission and count < len(mission['notes']) else None
                highlighted = state['note'] if state['note_until'] > now else None
                draw_keyboard(cv2, view, layout, (bx, by), (bw, bh), highlighted, target_note)

                timestamp_ms = max(last_timestamp + 1, int((now - begin) * 1000))
                last_timestamp = timestamp_ms
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                result = landmarker.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), timestamp_ms)
                observed = set()
                for hand_num, landmarks in enumerate(result.hand_landmarks or []):
                    hand_side = ('hand_' + str(hand_num))
                    if result.handedness and hand_num < len(result.handedness) and result.handedness[hand_num]:
                        hand_side = result.handedness[hand_num][0].category_name + '_' + str(hand_num)
                    for tip in FINGERTIPS:
                        lm = landmarks[tip]
                        px, py = lm.x * w, lm.y * h
                        if homography is not None:
                            pt = np.array([[[px, py]]], dtype=np.float32)
                            tx, ty = cv2.perspectiveTransform(pt, homography)[0][0]
                            hit_x, hit_y = float(tx), float(ty)
                            vx, vy = round(tx), round(ty)
                        else:
                            hit_x = (px - bx) * layout.width / bw
                            hit_y = (py - by) * layout.height / bh
                            vx, vy = round(px), round(py)
                        finger_key = (hand_side, tip)
                        # Smoothed point picks the key; raw motion still drives tap detection.
                        note, _, _ = smoother.key_for(finger_key, hit_x, hit_y, now)
                        relative_z = lm.z - landmarks[TIP_TO_MCP[tip]].z
                        observed.add(finger_key)
                        played = detector.update(finger_key, note, hit_y, relative_z, now)
                        dot_color = (60, 255, 90) if played else (50, 180, 255)
                        if 0 <= vx < view.shape[1] and 0 <= vy < view.shape[0]:
                            cv2.circle(view, (vx, vy), 6, dot_color, -1, cv2.LINE_AA)
                        if played:
                            sounds[played].play()
                            state['note'], state['note_until'] = played, now + .19
                            if args.mode == 'coach':
                                try:
                                    outcome = db.record_table_piano_tap(args.learner, played)
                                    state['message'] = outcome['message']
                                    state['progress'] = outcome
                                    if outcome['finished']:
                                        state['mission'] = None
                                        state['progress'] = None
                                        state['last_check'] = 0
                                        print('Mission completed:', outcome['message'])
                                except ValueError as exc:
                                    state['message'] = str(exc)[:110]
                            elif args.mode == 'jam':
                                if len(state['jam_notes']) < 20:
                                    state['jam_notes'].append(played)
                                state['message'] = f"Creative Jam: {len(state['jam_notes'])}/20 notes. Press J to ask coach."
                            else:
                                # Free mode: the tap becomes a key press on the ToneTutor page
                                # (free play, Learn the Notes and piano exercises).
                                try:
                                    db.record_webcam_tap(args.learner, played)
                                    state['message'] = f'Played {played}'
                                except ValueError as exc:
                                    state['message'] = str(exc)[:110]
                detector.forget_missing(observed)
                smoother.forget_missing(observed)

                if homography is None:
                    for i, (x, y) in enumerate(corners):
                        cv2.circle(view, (int(x), int(y)), 8, (0, 200, 255), -1)
                        cv2.putText(view, str(i + 1), (int(x) + 8, int(y)),
                                    cv2.FONT_HERSHEY_SIMPLEX, .7, (255, 255, 255), 2)
                if args.mode == 'coach':
                    info = ('Coach mode | plan a Guided Mission in Streamlit first' if not mission else
                            f'Coach: {mission["drill_id"]}  {count}/{len(mission["notes"])} correct | next {target_note}')
                elif args.mode == 'jam':
                    info = f'Creative Jam: {len(state["jam_notes"])} keys | Press J after 3-20 notes'
                else:
                    info = 'Free play: taps appear as key presses on the ToneTutor page'
                put_lines(cv2, view, [f'DEMO  Learner {args.learner} | {info}',
                                       ('Click corners TL -> TR -> BR -> BL | ' if homography is None else 'Calibrated | ')
                                       + 'Q quit  C recalibrate  J submit jam',
                                       state['message'][:110]])
                cv2.imshow(window, view)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord('q'), 27):
                    break
                if key == ord('c'):
                    corners.clear()
                    homography = None
                    detector.states.clear()
                    smoother.fingers.clear()
                    state['message'] = 'Calibration cleared. Click 4 desk corners.'
                if key == ord('j') and args.mode == 'jam':
                    notes = state['jam_notes']
                    if len(notes) < 3:
                        state['message'] = 'Play at least 3 notes before requesting Creative Jam advice.'
                    else:
                        state['message'] = 'Submitting phrase to piano coach...'
                        cv2.imshow(window, view)
                        cv2.waitKey(1)
                        try:
                            advice = respond_to_jam(args.learner, notes, args.controller)
                            db.save_webcam_jam_feedback(args.learner, advice)
                            state['message'] = f"{advice.get('title','Coach')}: {advice.get('prompt','')}"[:112]
                            print('Creative Jam response:', advice)
                            state['jam_notes'] = []
                        except Exception as exc:
                            state['message'] = 'Coach error: ' + str(exc)[:90]
    finally:
        cap.release()
        cv2.destroyAllWindows()
        pygame.quit()
        if args.stop_file:
            Path(args.stop_file).unlink(missing_ok=True)


if __name__ == '__main__':
    main()

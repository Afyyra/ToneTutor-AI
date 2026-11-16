# ToneTutor AI — Adaptive Music Tutor with AI Piano Coach

**Arena Solusi – Cabaran Agentic AI | Educational local prototype**

This version extends the corrected ToneTutor AI application with **agent-directed piano practice** and **open-ended creative exploration**. It is the same event-driven Gemini tutor, with additional learner-scoped, validated tools—not a new team of independent agents.

## Core application

- Seven screens: Dashboard, Lessons, Training, Piano, Notation, Schedule, Progress.
- Twelve chromatic pitch classes, 10 beginner lessons, and eight original exercise skills.
- A 24-key C4–B5 virtual piano with instant Web Audio playback.
- Six-question initial assessment, adaptive lessons, SQLite progress history, and optional Google Calendar scheduling.
- Gemini function calling through the Google Gen AI SDK; labelled deterministic `rules` fallback when unavailable.
- Learner-scoped tools and `source`-labelled execution logs.

## NEW: AI Piano Coach

On **Piano → AI Piano Coach**, choose one of two studios and choose an input method: **On-screen piano** or **Webcam table piano (MediaPipe)**:

### Guided Missions

1. Choose *Automatic*, *Key location*, *Melodic movement*, *Black keys*, or *Chord outlines*.
2. Ask the coach to plan the next mission.
3. The tutor retrieves recent keyboard mission accuracy and selects an **approved original note pattern** (12 validated drills covering three levels).
4. Play the pattern directly on the virtual piano. Every tap receives immediate, deterministic note-by-note feedback. Wrong keys are counted without pretending that they are correct.
5. Completing the phrase saves the result in SQLite. Ask for another mission; the tutor can use the new history to adapt.

**What the AI does:** selects a practical mission and provides a performance-based reason through the `get_piano_coach_context` and `set_piano_coach_mission` tools. **What Python does:** validates the selected drill, records learner-scoped data, checks every key press, and computes accuracy. Gemini is not called on every key press.

### Creative Jam

1. Play 3–20 notes freely on the virtual keyboard.
2. Choose **Ask the coach to respond to my phrase**.
3. Python describes observable features of the tapped notes (number of distinct notes, range, rising/falling steps, repeats, leaps).
4. The agent retrieves this history, chooses one of eight validated open-ended exploration prompts, and explains its selection.
5. Make another phrase using the creative suggestion. **Creativity is not graded as correct/incorrect.**

The model is called through `get_piano_jam_context` and `set_piano_jam_direction`. All these actions are logged as `gemini` or `rules` so judges can distinguish real function calling from fallback.

### Scope and limitations

- This is an **on-screen keyboard**, not microphone, singing, physical keyboard, MIDI input, fingering or audio-listening analysis.
- It tracks **pressed virtual keys**, not speed, precise rhythm, emotional expression or physical hand technique.
- Creative prompts are **preapproved original directions**, not arbitrary unverified or copyrighted songs.
- The learner can choose a goal, leave the coach, or cancel a mission without a score.
- Continued incorrect taps may extend the practice task; the interface is not a clinical pitch test.
- Assessment mastery and long-term educational effectiveness still require real learner trials.

## Setup on Windows

Copy this **ToneTutor_AI** folder as a complete project into a separate location. Keep your existing project safe until testing finishes. Do **not** overwrite a real `.env`, `credentials.json`, `google_token.json`, or existing `tonetutor_v2.db` with placeholder files; the ZIP intentionally contains none of them.

From PowerShell, inside the new `ToneTutor_AI` folder:

```powershell
..\venv\Scripts\python.exe -m pip install -r requirements.txt
..\venv\Scripts\python.exe -m streamlit run app.py
```

This assumes the virtual environment is a **sibling** of `ToneTutor_AI` (matching your earlier screenshot). If not, launch `START_TONETUTOR.bat` to create an isolated `.venv` inside the project using Python 3.11 or 3.12.

For live Gemini, copy `.env.example` to `.env` and set `GEMINI_API_KEY` and an available function-calling `GEMINI_MODEL`. In the sidebar, choose **Gemini AI**. Without a working model/API key, the app transparently uses **Offline rules**.

## Verify tests

```powershell
..\venv\Scripts\python.exe -m unittest discover -s tests -v
```

In this prepared package **29 automated tests passed locally**, including a mock Gemini piano-coach tool cycle and a mock creative-jam tool cycle. Tests do **not** prove successful live Gemini requests, browser click responsiveness, Google OAuth integration, or educational impact. Verify those separately on your demo laptop.

## Judge demonstration

- Select **Gemini AI** in the sidebar (make sure your API key works).
- Go to **Piano → AI Piano Coach → Guided Missions** and ask the coach for a mission.
- Play a wrong note, then the requested notes; show immediate feedback and saved accuracy.
- Ask for a follow-up mission and explain how the tool read the prior attempt.
- Switch to **Creative Jam**, play 4–6 keys, ask the coach for a creative direction.
- Open **Progress → Actual tool execution log**. Point out `source=gemini`. If the logs show `source=rules`, accurately state that the fallback controlled the demonstration.

Also see [`NABC_BMC_PRODUCT_CASE.md`](NABC_BMC_PRODUCT_CASE.md) for the need, approach, benefits, competition, and business model framing.

## Optional webcam-based table piano (MediaPipe)

This source also includes an **optional local desktop camera companion** implemented with MediaPipe Hand Landmarker, OpenCV perspective calibration and Pygame polyphonic playback. It supports two-octave C4–B5 keyboard hitboxes, a conservative motion-based **tap estimate**, live Guided Mission scoring saved to the same learner-scoped SQLite database, and Creative Jam phrase capture.

**Setup:** see [`TABLE_PIANO_SETUP.md`](TABLE_PIANO_SETUP.md). Install extra dependencies using `requirements-webcam.txt` **only if you use the webcam mode**. The Streamlit/Google Gen AI SDK framework and main `requirements.txt` are unchanged. A normal RGB webcam does not physically sense desk contact. All video is processed locally; it is not retained or sent to Gemini.


## Unified AI Webcam Piano Coach (NEW)

The MediaPipe table piano is now an **input method inside AI Piano Coach**, not a separate training mode. Choose **Piano → AI Piano Coach → Guided Missions/Creative Jam → Webcam table piano (MediaPipe)**. You can plan a mission and launch the local OpenCV camera with **one button**. Progress is displayed automatically inside Streamlit, and completed webcam missions inform the next Gemini-selected mission. Creative Jam directions from the webcam are visible in the same page.

The webcam preview still opens in its own local desktop window for table calibration and finger tracking; it is **not a live browser video stream**. Video remains local. Only note names, scores and coaching decisions are stored. See `UNIFIED_WEBCAM_COACH_SETUP.md` for Windows installation and the **Python 3.12** fix for Pygame. MediaPipe, OpenCV and Pygame are optional added libraries; the original Python/Streamlit/Gemini framework is unchanged.

## Webcam piano in the browser (works online)

Every piano mode, including AI Piano Coach, now offers three inputs under **How will you play?**:

- **On-screen piano**: click the keys.
- **Webcam in browser (works online)**: the camera, MediaPipe hand tracking and tap detection run inside the learner's own browser (`webcam_component/webcam_piano.mjs`). Only the note names that are tapped are sent to Python, so it also works when ToneTutor is hosted online. Keys are drawn in perspective over the live picture of your table; use **Calibrate corners** to fit them to a paper keyboard or table area.
- **Webcam window (this laptop only)**: the original OpenCV desktop window (`table_piano.py`). It uses the camera of the computer running Streamlit, so it cannot work on a hosted app.

The browser webcam needs Chrome or Edge on an `https://` or `localhost` page and camera permission. The first start downloads the MediaPipe hand model (a few seconds). Python still checks every answer and mission exactly as for on-screen key presses. Its keyboard layout and tap detector are ports of `table_piano_core.py`, and `tests/test_browser_webcam.py` checks them against the Python originals (using Node.js when available).

## Deploy online (Streamlit Community Cloud)

1. Sign in at share.streamlit.io with GitHub and choose **Create app**.
2. Pick this repository, branch `main`, main file `app.py`, and Python 3.12 under **Advanced settings**.
3. Optional: add `GEMINI_API_KEY` and `GEMINI_MODEL` under **Secrets**. Without a key the app runs on the offline rules.

On a hosted app all visitors share one SQLite database that may reset when the app restarts, every visitor's AI planning uses the configured Gemini key, and Google Calendar sign-in is not available.

"""Twelve-tone equal temperament, music-theory helpers, and ten beginner lessons.
Enharmonic spellings share a pitch; A4 = 440 Hz. No external sound files.
"""
import math
import re

PITCH_CLASSES = ('C','C#','D','D#','E','F','F#','G','G#','A','A#','B')
FLAT_TO_SHARP = {'Db':'C#','Eb':'D#','Gb':'F#','Ab':'G#','Bb':'A#'}
SHARP_TO_FLAT = {'C#':'Db','D#':'Eb','F#':'Gb','G#':'Ab','A#':'Bb'}
NATURAL = ('C','D','E','F','G','A','B')
WHITE_KEYS = tuple(f'{n}{o}' for o in (4,5) for n in NATURAL)
ALL_KEYS = tuple(f'{n}{o}' for o in (4,5) for n in PITCH_CLASSES)


def normalise(note):
    if not isinstance(note, str):
        raise ValueError('Note must be text')
    text = note.strip().replace('♯','#').replace('♭','b')
    match = re.fullmatch(r'([A-Ga-g])([#b]?)(-?\d)', text)
    if not match:
        raise ValueError('Use a note like C4, F#4, or Bb4')
    name, accidental, octave = match.groups()
    name = name.upper() + accidental
    name = FLAT_TO_SHARP.get(name, name)
    if name not in PITCH_CLASSES or not 0 <= int(octave) <= 9:
        raise ValueError('Unsupported note or octave')
    return f'{name}{octave}'


def midi(note):
    note = normalise(note)
    # C4 = 60; A4 = 69
    return 12 * (int(note[-1]) + 1) + PITCH_CLASSES.index(note[:-1])


def note_from_midi(number, prefer_flats=False):
    if not isinstance(number, int) or not 0 <= number <= 127:
        raise ValueError('Invalid MIDI note')
    pc = PITCH_CLASSES[number % 12]
    return f'{SHARP_TO_FLAT.get(pc,pc) if prefer_flats else pc}{number//12-1}'


def frequency(note):
    return 440.0 * 2 ** ((midi(note) - 69) / 12)


def semitones(a, b):
    return midi(b) - midi(a)


def scale(root='C4', minor=False):
    pattern = (0,2,3,5,7,8,10,12) if minor else (0,2,4,5,7,9,11,12)
    return [note_from_midi(midi(root)+step) for step in pattern]


def chord(root='C4', kind='major'):
    patterns = {'major':(0,4,7),'minor':(0,3,7),'diminished':(0,3,6)}
    if kind not in patterns: raise ValueError('Unknown chord')
    return [note_from_midi(midi(root)+step) for step in patterns[kind]]


def note_info(note):
    n = normalise(note)
    return {'name':n,'frequency_hz':round(frequency(n),2),
            'enharmonic': SHARP_TO_FLAT.get(n[:-1],n[:-1])+n[-1],
            'octave':int(n[-1]),'key_type':'black' if '#' in n else 'white'}

LESSONS = [
    {'id':'pitch','title':'1 · Sound, Pitch & Frequency','skill':'pitch', 'level':'Foundation',
     'text':'Pitch tells us how high or low a sound is. Higher frequency means higher pitch, not greater loudness. Frequency is measured in hertz (Hz). A4 vibrates at 440 Hz.',
     'example':'Play C4 and C5. C5 has twice the frequency and is one octave higher.', 'audio':['C4','C5']},
    {'id':'alphabet','title':'2 · Musical Alphabet & 12 Notes','skill':'notes','level':'Foundation',
     'text':'The seven natural notes are A B C D E F G. There are 12 different pitch classes in an octave: C C# D D# E F F# G G# A A# B. These repeat in higher and lower octaves.',
     'example':'Listen to C4, C#4 and D4. Adjacent keys are one semitone apart.', 'audio':['C4','C#4','D4']},
    {'id':'accidentals','title':'3 · Sharps, Flats & Naturals','skill':'theory','level':'Foundation',
     'text':'A sharp (#) raises a pitch by one semitone; a flat (♭) lowers it by one. C# and Db normally sound the same in equal temperament (enharmonic notes). A natural sign (♮) cancels an earlier accidental.',
     'example':'C#4 and Db4 are two names for the same piano key.', 'audio':['C4','C#4']},
    {'id':'steps','title':'4 · Semitones, Whole Tones & Octaves','skill':'intervals','level':'Foundation',
     'text':'A semitone is the distance from a piano key to the next key, white or black. A whole tone is two semitones. An octave is 12 semitones and doubles the frequency.',
     'example':'E4 to F4 = one semitone; C4 to D4 = one whole tone.', 'audio':['E4','F4','C4','D4']},
    {'id':'scales','title':'5 · Major & Minor Scales','skill':'theory','level':'Developing',
     'text':'A major scale follows 2-2-1-2-2-2-1 semitone steps. Natural minor follows 2-1-2-2-1-2-2. The starting note is called the tonic. C major has no sharps or flats.',
     'example':'Compare C major (C D E F G A B C) and A natural minor (A B C D E F G A).', 'audio':['C4','D4','E4','F4','G4','A4','B4','C5']},
    {'id':'intervals','title':'6 · Musical Intervals','skill':'intervals','level':'Developing',
     'text':'An interval describes the distance between two notes. Examples: minor second = 1 semitone, major second = 2, major third = 4, perfect fourth = 5, perfect fifth = 7, octave = 12.',
     'example':'Listen to C4 followed by G4: a perfect fifth of seven semitones.', 'audio':['C4','G4']},
    {'id':'chords','title':'7 · Basic Chords & Progressions','skill':'theory','level':'Developing',
     'text':'A major triad stacks a root, major third (+4), and perfect fifth (+7). A minor triad uses +3 and +7. A progression is a sequence of chords; I–IV–V–I in C major is C–F–G–C.',
     'example':'Play C4-E4-G4, then C4-Eb4-G4 to compare major and minor.', 'audio':['C4','E4','G4']},
    {'id':'rhythm','title':'8 · Rhythm, Tempo & Time Signatures','skill':'rhythm','level':'Foundation',
     'text':'Tempo is speed, often measured in beats per minute (BPM). In 4/4, each measure normally contains four quarter-note beats. Whole = 4 beats, half = 2, quarter = 1, eighth = 1/2; rests indicate silence.',
     'example':'Clap four equally spaced beats: 1, 2, 3, 4. Then clap two beats per bar in 2/4.', 'audio':['C4']},
    {'id':'notation','title':'9 · Read the Musical Staff','skill':'notation','level':'Developing',
     'text':'The staff has five lines and four spaces. Treble lines (bottom-up): E G B D F; spaces: F A C E. Bass lines: G B D F A; spaces: A C E G. Ledger lines extend beyond the staff. Whole/half/quarter/eighth note shapes show duration.',
     'example':'Treble E4 sits on the bottom line; middle C4 sits on a ledger line below the staff.', 'audio':['C4','E4','G4']},
    {'id':'melody','title':'10 · Hearing & Playing Melodies','skill':'melody','level':'Developing',
     'text':'A melody is a sequence of pitches in time. Listen for direction (up/down), repeating notes, and stepwise movement. Start with short phrases; use the keyboard to reproduce them.',
     'example':'Listen to C4 D4 E4 G4. Try singing or playing the sequence slowly.', 'audio':['C4','D4','E4','G4']},
]
LESSON_BY_ID = {lesson['id']:lesson for lesson in LESSONS}

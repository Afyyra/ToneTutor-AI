"""Parameterized exercises: every assignment is generated afresh and persisted with its answer key."""
import random
import uuid
from copy import deepcopy
from music import PITCH_CLASSES, note_from_midi, midi, semitones, scale, chord, LESSON_BY_ID

SKILLS = ('pitch','notes','intervals','theory','rhythm','notation','melody','piano')
LEVELS = ('easy','medium','hard')
EXERCISE_TYPES = {'pitch':('compare_pitch',),'notes':('identify_note','contrast_notes'),
                  'intervals':('interval_audio',),'theory':('theory','scale_quiz','chord_quiz'),
                  'rhythm':('rhythm_quiz',),'notation':('staff_note',),
                  'melody':('melody_repeat',),'piano':('piano_follow','piano_note')}
THEORY_BANK = [
 ('alphabet','How many different pitch classes exist in an octave?', ['7','12','14'],'12','There are 12 pitch classes, including sharp/flat keys.'),
 ('accidentals','What does a sharp (#) usually do?', ['Raises one semitone','Lowers one semitone','Raises an octave'],'Raises one semitone','A sharp raises the pitch by one semitone.'),
 ('accidentals','What other name is commonly used for C#?', ['Db','Eb','D#'],'Db','C# and Db are enharmonic in equal temperament.'),
 ('steps','How many semitones are in a whole tone?', ['1','2','12'],'2','A whole tone consists of two semitones.'),
 ('steps','What happens to frequency an octave higher?', ['Halves','Doubles','Stays the same'],'Doubles','A musical octave corresponds to twice the frequency.'),
 ('scales','What is the major-scale interval pattern?', ['2-2-1-2-2-2-1','2-1-2-2-1-2-2','1-1-2-2-1-3-2'],'2-2-1-2-2-2-1','Major scales follow the W-W-H-W-W-W-H pattern.'),
 ('scales','Which notes belong to C major?', ['C D E F G A B','C D Eb F G A B','C D E F# G A B'],'C D E F G A B','C major uses only natural notes.'),
 ('chords','Which notes make a C major triad?', ['C E G','C Eb G','C F A'],'C E G','A major triad is root +4 +7 semitones.'),
 ('chords','Which chord progression is I–IV–V–I in C major?', ['C–F–G–C','C–D–E–C','C–G–A–C'],'C–F–G–C','The tonic, subdominant, and dominant chords of C major are C, F, and G.'),
 ('rhythm','How many quarter-note beats are in a standard 4/4 measure?', ['2','3','4'],'4','4/4 counts four quarter-note beats per bar.'),
 ('rhythm','How many quarter-note beats is a half note worth in 4/4?', ['1','2','4'],'2','Half note = 2 quarter-note beats.'),
 ('notation','How many lines are on a standard musical staff?', ['4','5','6'],'5','A staff has five lines and four spaces.'),
 ('notation','What does a ledger line do?', ['Extends the staff','Marks a new tempo','Cancels a sharp'],'Extends the staff','Ledger lines are short extensions for notes above or below the staff.'),
 ('intervals','A perfect fifth spans how many semitones?', ['5','7','12'],'7','A perfect fifth spans seven semitones.'),
 ('pitch','Is a louder note necessarily higher in pitch?', ['Yes','No'],'No','Loudness and pitch are different properties.'),
]

def _exercise(skill, difficulty, typ, question, notes, options, answer, explanation, topic=None, meta=None):
    return dict(id=uuid.uuid4().hex[:16],skill=skill,difficulty=difficulty,type=typ,
                question=question,notes=notes,options=options,correct_answer=answer,
                explanation=explanation,topic=topic or skill,meta=meta or {})

def _choose_note(rng, difficulty, focus_note=None):
    choices={'easy':['C4','D4','E4','F4','G4'], 'medium':[f'{p}4' for p in PITCH_CLASSES],
             'hard':[f'{p}{o}' for o in (4,5) for p in PITCH_CLASSES]}[difficulty]
    if focus_note and focus_note in choices and rng.random()<.76:
        return focus_note
    return rng.choice(choices)

def generate(skill, difficulty='easy', *, focus_note=None, contrast_note=None, preferred_type=None, topic=None, rng=None):
    if skill not in SKILLS or difficulty not in LEVELS: raise ValueError('Unknown skill/difficulty')
    if preferred_type is not None and preferred_type not in EXERCISE_TYPES[skill]:
        raise ValueError('Invalid exercise type for skill')
    rng=rng or random.SystemRandom()
    typ=preferred_type or rng.choice(EXERCISE_TYPES[skill])
    if skill=='pitch':
        dist={'easy':[7,12], 'medium':[3,4,5], 'hard':[1,2]}[difficulty]
        distance=rng.choice(dist)
        start=rng.randint(48,76-distance)
        pair=[note_from_midi(start),note_from_midi(start+distance)]
        rng.shuffle(pair)
        correct='Sound A' if midi(pair[0])>midi(pair[1]) else 'Sound B'
        return _exercise(skill,difficulty,typ,'Which sound is higher in pitch?',pair,['Sound A','Sound B'],correct,
                        f'{correct} is higher. The notes are {pair[0]} and {pair[1]} ({distance} semitones apart).',
                        meta={'distance':distance})
    if skill=='notes':
        chosen=_choose_note(rng,difficulty,focus_note)
        size={'easy':3,'medium':5,'hard':8}[difficulty]
        pool=[f'{p}{chosen[-1]}' for p in PITCH_CLASSES]
        if typ=='contrast_notes' and contrast_note and contrast_note in pool and contrast_note!=chosen:
            other=contrast_note
            answers=[chosen,other]
        else:
            distractors=[n for n in pool if n!=chosen]
            # Prefer nearby pitch classes; makes listening rather than guessing important.
            distractors.sort(key=lambda n:abs(midi(n)-midi(chosen)))
            nearby=distractors[:max(4,size+1)]
            answers=[chosen]+rng.sample(nearby,min(size-1,len(nearby)))
        rng.shuffle(answers)
        return _exercise(skill,difficulty,typ,'Listen and identify the note. Replay labelled reference tones if needed.',
                        [chosen],answers,chosen,
                        f'You heard {chosen} ({round(440*2**((midi(chosen)-69)/12),1)} Hz). Compare its sound with nearby notes.',
                        topic='alphabet',meta={'focus_note':chosen,'contrast_note':contrast_note})
    if skill=='intervals':
        distance=rng.choice({'easy':[1,2,12],'medium':[3,4,5,7],'hard':[6,8,9,10,11]}[difficulty])
        start=rng.randint(58,74-distance)
        notes=[note_from_midi(start),note_from_midi(start+distance)]
        options=[f'{n} semitones' for n in (1,2,3,4,5,6,7,8,9,10,11,12)]
        decoys=rng.sample([n for n in options if n!=f'{distance} semitones'],3)
        choices=[f'{distance} semitones']+decoys
        rng.shuffle(choices)
        return _exercise(skill,difficulty,typ,'Listen to the two notes. How far apart are they?',notes,
                        choices,f'{distance} semitones',f'They are {distance} semitones apart.',topic='intervals')
    if skill=='theory' or skill=='rhythm':
        if typ=='scale_quiz':
            root=rng.choice(['C4','G4','D4','A4'])
            minor=rng.choice([True,False])
            sequence=scale(root,minor)
            answer=' / '.join(sequence[:4])
            wrong=[' / '.join(scale(root,not minor)[:4]),' / '.join(sequence[1:5])]
            answers=list(dict.fromkeys([answer]+wrong))
            rng.shuffle(answers)
            return _exercise('theory',difficulty,typ,f'Which first four notes belong to {root[:-1]} {"natural minor" if minor else "major"}?',
                             sequence,answers,answer,'Listen to the scale and notice its step pattern.',topic='scales')
        if typ=='chord_quiz':
            root=rng.choice(['C4','D4','F4','G4'])
            kind=rng.choice(['major','minor'])
            correct=chord(root,kind)
            answer=' + '.join(correct)
            wrong=[' + '.join(chord(root,'minor' if kind=='major' else 'major')),' + '.join([root,note_from_midi(midi(root)+5),note_from_midi(midi(root)+7)])]
            options=list(dict.fromkeys([answer]+wrong));rng.shuffle(options)
            return _exercise('theory',difficulty,typ,f'Which notes form a {root[:-1]} {kind} triad?',correct,
                            options,answer,'Major triads use +4,+7; minor use +3,+7.',topic='chords')
        bank=[b for b in THEORY_BANK if (skill=='rhythm')== (b[0]=='rhythm')]
        if topic: bank=[b for b in bank if b[0]==topic] or bank
        item=rng.choice(bank)
        opts=item[2][:];rng.shuffle(opts)
        return _exercise(skill,difficulty,'rhythm_quiz' if skill=='rhythm' else 'theory',item[1],[],opts,item[3],item[4],topic=item[0])
    if skill=='notation':
        clef=rng.choice(['treble','bass']) if difficulty!='easy' else 'treble'
        options_pool={'treble':['C4','D4','E4','F4','G4','A4','B4','C5','D5','E5','F5'],
                      'bass':['C3','D3','E3','F3','G3','A3','B3','C4','D4']}
        subset=options_pool[clef][:7 if difficulty=='easy' else 11]
        chosen=rng.choice(subset)
        others=rng.sample([n for n in options_pool[clef] if n!=chosen],3)
        opts=[chosen]+others;rng.shuffle(opts)
        return _exercise(skill,difficulty,typ,f'What note is shown on the {clef} clef staff?',
                         [chosen],opts,chosen,f'The staff note is {chosen}.',topic='notation',meta={'clef':clef})
    if skill in ('melody','piano'):
        length={'easy':3,'medium':4,'hard':5}[difficulty]
        pool=['C4','D4','E4','G4'] if difficulty=='easy' else ([f'{p}4' for p in ['C','D','E','F','G','A','B']] if difficulty=='medium' else [f'{p}4' for p in PITCH_CLASSES])
        if skill=='piano':
            seq=[rng.choice(pool) for _ in range(length)]
            if typ=='piano_note': seq=seq[:1]
            question=('Find and play this note on the piano:' if typ=='piano_note' else 'Play these notes in order on the piano:')
            return _exercise(skill,difficulty,typ,question,seq,[],seq,
                            'Compare your played sequence with the displayed target notes.',topic='melody')
        # Mix generated phrases with recognizable public-domain excerpts (no copyrighted recordings).
        public_domain={'easy': [('Little Rising Phrase',['C4','D4','E4'])],
                       'medium':[('Twinkle, Twinkle opening',['C4','C4','G4','G4'])],
                       'hard':[('Ode to Joy opening',['E4','E4','F4','G4','G4','F4','E4','D4'])]}
        if rng.random()<0.35:
            title,seq=rng.choice(public_domain[difficulty])
            return _exercise(skill,difficulty,typ,
                  f'Listen to the {title}. Play the notes in the same order.',seq,[],seq,
                  'The notes were '+', '.join(seq)+'.',topic='melody',meta={'melody':title})
        seq=[rng.choice(pool)]
        for _ in range(length-1):
            nearby=sorted(pool,key=lambda n:abs(midi(n)-midi(seq[-1])))[:4]
            seq.append(rng.choice(nearby))
        return _exercise(skill,difficulty,typ,'Listen and reproduce the note sequence using the virtual piano.',seq,[],seq,
                        'The melody was '+', '.join(seq)+'.',topic='melody')
    raise AssertionError('Unhandled exercise')


def public(ex):
    # Notation notes need to be in the image; piano-follow targets are intentionally visible.
    obj={k:deepcopy(v) for k,v in ex.items() if k not in ('correct_answer','explanation')}
    if ex['type'] in ('identify_note','contrast_notes','melody_repeat'):
        # audio renderer must receive the pitches locally, but never print them as labels pre-answer
        pass
    return obj


def grade(ex, submitted):
    answer=ex['correct_answer']
    if isinstance(answer,list):
        if not isinstance(submitted,list): raise ValueError('Submit a note sequence')
        if len(submitted)>16: raise ValueError('Sequence too long')
        match=[i<len(submitted) and submitted[i]==note for i,note in enumerate(answer)]
        return {'correct':len(submitted)==len(answer) and all(match),
                'partial':sum(match),'total':len(answer),'by_note':match,
                'correct_answer':answer,'explanation':ex['explanation']}
    if submitted not in ex['options']: raise ValueError('Choose one of the given answers')
    return {'correct':submitted==answer,'partial':int(submitted==answer),'total':1,
            'correct_answer':answer,'explanation':ex['explanation']}

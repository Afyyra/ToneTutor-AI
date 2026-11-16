"""Agent-directed, event-driven keyboard coaching, distinct from conventional scored quizzes.

The same single Gemini tutor can plan a piano mission by calling constrained tools.
The browser plays notes, while deterministic Python compares each played note to the
next target. Feedback is immediate; the model is only called BETWEEN missions.
"""
import os

import database as db
from music import ALL_KEYS, midi
from runtime_tls import validate_ca_bundle

# Original, short instructional patterns rather than imported/copyrighted songs.
# Each goal has safe, teacher-readable drills at increasing difficulty levels.
DRILLS = {
    'middle_c': dict(goal='Key location', level='easy', title='Find middle C', notes=['C4', 'D4', 'C4'],
                     tip='Find C4 to the left of the group of two black keys, then move one white key right.'),
    'white_steps': dict(goal='Key location', level='medium', title='Neighbouring white keys', notes=['C4','D4','E4','F4'],
                        tip='Move to the very next white key each time. Keep the keyboard map in view.'),
    'octave_map': dict(goal='Key location', level='hard', title='Find the octave', notes=['C4','G4','C5','B4','C5'],
                       tip='C4 and C5 share a letter name, but are twelve semitones apart.'),
    'rising_three': dict(goal='Melodic movement', level='easy', title='A gentle climb', notes=['C4','D4','E4'],
                         tip='Play each adjacent white key in order, listening as the notes rise.'),
    'up_and_down': dict(goal='Melodic movement', level='medium', title='Climb and return', notes=['C4','D4','E4','D4','C4'],
                        tip='Hear the phrase rise, turn, and then descend back to C4.'),
    'melodic_leaps': dict(goal='Melodic movement', level='hard', title='Wider melodic leaps', notes=['C4','E4','G4','E4','C5'],
                         tip='Look ahead at the next target and find it before pressing a key.'),
    'black_neighbor': dict(goal='Black keys', level='easy', title='Meet C-sharp', notes=['C4','C#4','D4'],
                           tip='C-sharp is the black key between the white C and D keys.'),
    'black_steps': dict(goal='Black keys', level='medium', title='Chromatic neighbours', notes=['F4','F#4','G4','G#4','A4'],
                        tip='Each step moves to an adjacent key; black keys count as semitone steps.'),
    'black_pattern': dict(goal='Black keys', level='hard', title='Navigate the black keys', notes=['C#4','D#4','F#4','G#4','A#4'],
                          tip='Find the groups of two and three black keys before playing.'),
    'triad_start': dict(goal='Chord outlines', level='easy', title='Outline a C-major chord', notes=['C4','E4','G4'],
                        tip='A C-major triad has the notes C, E, and G. Play them separately.'),
    'arpeggio': dict(goal='Chord outlines', level='medium', title='C-major arpeggio', notes=['C4','E4','G4','C5'],
                     tip='An arpeggio plays a chord one note at a time, ascending to C5.'),
    'chord_motion': dict(goal='Chord outlines', level='hard', title='Two chord outlines', notes=['C4','E4','G4','D4','F#4','A4'],
                         tip='First outline C major, then D major. Notice the F-sharp black key.'),
}
GOALS = ('Automatic', 'Key location', 'Melodic movement', 'Black keys', 'Chord outlines')
LEVELS = ('easy','medium','hard')


def public_mission(row):
    if not row:
        return None
    detail=DRILLS[row['drill_id']]
    return {**row,'title':detail['title'],'goal':detail['goal'],'difficulty':detail['level'],
            'notes':list(detail['notes']),'tip':detail['tip']}


def get_context(learner_id):
    """Only this learner's data is exposed to the piano coach."""
    return {'piano_history':db.coach_history(learner_id,limit=10),
            'skill_summary':{k:v for k,v in db.get_profile(learner_id)['skills'].items()
                             if k in ('piano','melody','notes')},
            'drills':[{'id':k,'goal':v['goal'],'difficulty':v['level'],
                       'title':v['title'],'length':len(v['notes'])} for k,v in DRILLS.items()]}


class PianoCoachTools:
    """A bounded tool set: inspect learner context and choose a validated keyboard drill."""
    def __init__(self,learner_id,source='gemini',goal='Automatic'):
        if goal not in GOALS:raise ValueError('Unknown piano coaching goal')
        self.learner_id=learner_id
        self.source=source
        self.goal=goal

    def execute(self,name,arguments=None):
        try:
            if not isinstance(arguments or {},dict):raise ValueError('Tool arguments must be an object')
            if name=='get_piano_coach_context':
                if arguments:raise ValueError('Context tool accepts no arguments')
                result=get_context(self.learner_id)
            elif name=='set_piano_coach_mission':
                if set(arguments or {})!={'drill_id','reason'}:
                    raise ValueError('A valid drill_id and short reason are required')
                drill_id=arguments['drill_id']
                reason=arguments['reason']
                if drill_id not in DRILLS:raise ValueError('Unknown piano drill')
                if self.goal!='Automatic' and DRILLS[drill_id]['goal']!=self.goal:
                    raise ValueError('Selected drill does not match the learner\'s chosen goal')
                if not isinstance(reason,str) or not reason.strip() or len(reason)>240:
                    raise ValueError('Reason must contain 1–240 characters')
                drill=DRILLS[drill_id]
                row=db.start_coach_mission(self.learner_id,drill_id,drill['notes'],reason)
                result={'mission':public_mission(row),'created':row['drill_id']==drill_id}
            else:
                raise ValueError('Piano coach tool not allowed')
        except Exception as exc:
            result={'error':str(exc) if isinstance(exc,(ValueError,TypeError)) else 'Piano coach tool failed'}
        db.log_tool(self.learner_id,name,arguments or {},result,self.source)
        return result


def offline_mission(learner_id,goal='Automatic'):
    """Transparent, reproducible fallback with difficulty adaptation and variety."""
    t=PianoCoachTools(learner_id,source='rules',goal=goal)
    ctx=t.execute('get_piano_coach_context')
    history=ctx['piano_history']
    candidates=[(key,drill) for key,drill in DRILLS.items()
                if goal=='Automatic' or drill['goal']==goal]
    previous=history[0] if history else None
    # Stay at easy initially; two strong recent outcomes unlock harder material.
    if len(history)>=2 and all(r['accuracy']>=0.85 for r in history[:2]):
        target_level='hard' if all(r['difficulty']=='medium' and r['accuracy']>=0.9 for r in history[:2]) else 'medium'
    elif previous and previous['accuracy']<0.7:
        target_level='easy'
    else:
        target_level=previous['difficulty'] if previous else 'easy'
    recent_ids=[r['drill_id'] for r in history[:3]]
    def score(pair):
        key,drill=pair
        return (abs(LEVELS.index(drill['level'])-LEVELS.index(target_level)),
                recent_ids.count(key),
                sum(h['drill_id']==key for h in history),
                list(DRILLS).index(key))
    drill_id,_=min(candidates,key=score)
    reason=('Start with a short keyboard-navigation mission.' if not previous else
            f"Based on the last piano mission ({previous['accuracy']:.0%} note accuracy), practise "
            f"{DRILLS[drill_id]['goal'].lower()} at {DRILLS[drill_id]['level']} level.")
    result=t.execute('set_piano_coach_mission',{'drill_id':drill_id,'reason':reason})
    if 'error' in result:raise RuntimeError(result['error'])
    return {'mode':'rules','mission':result['mission'],'reason':reason}


def _declarations(types):
    return [
      types.FunctionDeclaration(name='get_piano_coach_context',
        description='Read this learner\'s recent piano mistakes and the catalogue of permitted piano missions.',
        parameters_json_schema={'type':'object','properties':{},'required':[]}),
      types.FunctionDeclaration(name='set_piano_coach_mission',
        description='Set exactly one approved piano mission for this learner; includes an educational reason.',
        parameters_json_schema={'type':'object','properties':{
           'drill_id':{'type':'string','enum':list(DRILLS)},
           'reason':{'type':'string'}},'required':['drill_id','reason']}),
    ]


def gemini_mission(learner_id,goal='Automatic'):
    validate_ca_bundle()
    if not os.getenv('GEMINI_API_KEY'):
        raise RuntimeError('GEMINI_API_KEY is not configured')
    from google import genai
    from google.genai import types
    t=PianoCoachTools(learner_id,source='gemini',goal=goal)
    client=genai.Client(api_key=os.environ['GEMINI_API_KEY'])
    tool=types.Tool(function_declarations=_declarations(types))
    system=(
      'You are ToneTutor\'s keyboard coaching capability, part of the SAME single learning agent. '
      'Choose a short piano mission, not a chat-only suggestion. First CALL get_piano_coach_context; '
      'then CALL set_piano_coach_mission with one drill_id from the returned catalogue and a concise, '
      'learner-friendly performance-based reason. Focus on recent errors, sensible progression, and variety. '
      'Do not invent notes, grade answers, create arbitrary content, or pretend that the keyboard detects '
      'fingering, rhythm, emotion, or microphone audio. The deterministic piano engine evaluates played notes. '
      'If the learner selected a particular goal, honour it. Never access other learners.'
    )
    instruction=(f'Learner selected piano-coaching goal: {goal!r}. '
                 'Select one suitable practical keyboard mission, using the tools. '
                 'Consider recent accuracy and do not merely repeat the last drill if there is a better choice.')
    history=[types.Content(role='user',parts=[types.Part.from_text(text=instruction)])]
    call_count=0
    for _ in range(5):
        response=client.models.generate_content(
            model=os.getenv('GEMINI_MODEL','gemini-3.5-flash-lite'),contents=history,
            config=types.GenerateContentConfig(system_instruction=system,tools=[tool],temperature=0.2,
                      automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)))
        calls=response.function_calls or []
        if not calls or not response.candidates:break
        history.append(response.candidates[0].content)
        results=[]
        for call in calls:
            call_count+=1
            if call_count>8:raise RuntimeError('Piano coach tool budget exceeded')
            outcome=t.execute(call.name,{k:v for k,v in dict(call.args or {}).items() if v is not None})
            results.append(types.Part.from_function_response(name=call.name,response={'result':outcome}))
        history.append(types.Content(role='user',parts=results))
        mission=db.coach_active(learner_id)
        if mission:
            return {'mode':'gemini','mission':public_mission(mission),'tool_calls':call_count}
    raise RuntimeError('Gemini did not choose a valid piano mission')


def next_piano_mission(learner_id,mode='rules',goal='Automatic'):
    existing=db.coach_active(learner_id)
    if existing:return {'mode':'existing','mission':public_mission(existing)}
    if mode=='gemini':
        try:return gemini_mission(learner_id,goal)
        except Exception as exc:
            result=offline_mission(learner_id,goal)
            result['warning']='Gemini Piano Coach was unavailable; offline rules selected this mission. '+str(exc)[:180]
            return result
    return offline_mission(learner_id,goal)


def process_piano_press(current_notes,played_note,press_history):
    """Pure deterministic per-key feedback; records every tap, not just correct taps."""
    if not isinstance(current_notes,list) or not (1<=len(current_notes)<=12):
        raise ValueError('Invalid target notes')
    if played_note not in ALL_KEYS:raise ValueError('Invalid played note')
    if not isinstance(press_history,list) or len(press_history)>=80:raise ValueError('Practice attempt limit reached')
    progress=0
    for tap in press_history:
        if tap.get('correct'):progress+=1
    if progress>=len(current_notes):return {'history':press_history,'progress':progress,'finished':True}
    expected=current_notes[progress]
    correct=(played_note==expected)
    new_history=[*press_history,{'note':played_note,'expected':expected,'correct':correct}]
    progress+=int(correct)
    return {'history':new_history,'progress':progress,'finished':progress==len(current_notes),
            'message':('Correct, continue to the next note.' if correct else
                       f'You played {played_note}; find {expected} and try again.')}


# Unscored, creative piano dialogue. The model chooses a safe original exploration
# prompt, while Python observes the played notes and computes descriptive features.
JAM_DIRECTIONS={
 'motif_variation': ('Repeat and vary',
    'Choose any three-note idea you played. Repeat it once, then change only the final note.'),
 'answer_phrase': ('Call and response',
    'Play a short musical question, pause, then answer with a different three-note idea.'),
 'opposite_motion': ('Change direction',
    'If your last idea rose, make the next idea descend. If it fell, make the next idea rise.'),
 'smaller_steps': ('Try smaller moves',
    'Build a new idea using mostly adjacent piano keys and listen to how the contour changes.'),
 'wider_leaps': ('Explore a leap',
    'Start with nearby notes, then add one larger leap to give your phrase a different shape.'),
 'pentatonic_colors': ('Explore a five-note palette',
    'Freely explore C4, D4, E4, G4, and A4. Find an original pattern you enjoy.'),
 'rhythmic_play': ('Change the feel',
    'Replay your idea, changing the pauses between notes. The app cannot score rhythm; listen and reflect.'),
 'home_note': ('Find a musical ending',
    'Play a short phrase and try finishing on C4 or C5. Listen to whether it feels settled.'),
}


def describe_jam(notes):
    """No emotion or fingering inference; only objective properties of tapped keys."""
    if not isinstance(notes,list) or not (3<=len(notes)<=20) or any(n not in ALL_KEYS for n in notes):
        raise ValueError('Play 3–20 supported notes first')
    positions=[midi(n) for n in notes]
    differences=[b-a for a,b in zip(positions,positions[1:])]
    return {'notes_played':len(notes),'unique_notes':len(set(notes)),
            'pitch_range_semitones':max(positions)-min(positions),
            'ascending_steps':sum(d>0 for d in differences),
            'descending_steps':sum(d<0 for d in differences),
            'repeated_notes':sum(d==0 for d in differences),
            'large_leaps':sum(abs(d)>=5 for d in differences),
            'first_note':notes[0],'last_note':notes[-1]}


class JamCoachTools:
    def __init__(self,learner_id,source='gemini'):
        self.learner_id=learner_id;self.source=source;self.chosen=None

    def execute(self,name,arguments=None):
        args=arguments or {}
        try:
            if not isinstance(args,dict):raise ValueError('Tool arguments must be an object')
            if name=='get_piano_jam_context':
                if args:raise ValueError('Read-only tool takes no arguments')
                result={'recent_phrases':db.jam_history(self.learner_id,4),
                        'available_directions':[{'id':k,'title':v[0]} for k,v in JAM_DIRECTIONS.items()]}
            elif name=='set_piano_jam_direction':
                if set(args)!={'direction_id','reason'}:raise ValueError('Direction ID and reason are required')
                direction_id=args['direction_id'];reason=args['reason']
                if direction_id not in JAM_DIRECTIONS:raise ValueError('Unknown creative direction')
                if not isinstance(reason,str) or not reason.strip() or len(reason)>240:
                    raise ValueError('Reason must be 1–240 characters')
                self.chosen={'direction_id':direction_id,'title':JAM_DIRECTIONS[direction_id][0],
                             'prompt':JAM_DIRECTIONS[direction_id][1],'reason':reason}
                result={'selected':True,**self.chosen}
            else:raise ValueError('Piano jam tool not allowed')
        except Exception as exc:
            result={'error':str(exc) if isinstance(exc,(ValueError,TypeError)) else 'Jam tool execution failed'}
        db.log_tool(self.learner_id,name,args,result,self.source)
        return result


def offline_jam(learner_id):
    t=JamCoachTools(learner_id,source='rules')
    ctx=t.execute('get_piano_jam_context')
    if not ctx['recent_phrases']:raise ValueError('Play and record a phrase first')
    last=ctx['recent_phrases'][0];features=last['features']
    if features['repeated_notes']>=2:choice='motif_variation'
    elif features['large_leaps']>=2:choice='smaller_steps'
    elif features['ascending_steps']>features['descending_steps']+1:choice='opposite_motion'
    elif features['unique_notes']<=3:choice='pentatonic_colors'
    else:choice='answer_phrase'
    reason=(f"I noticed {features['unique_notes']} distinct keys and "
            f"{features['large_leaps']} large jumps in your last {features['notes_played']}-note idea. "
            'Here is a creative direction to explore next.')
    result=t.execute('set_piano_jam_direction',{'direction_id':choice,'reason':reason})
    return {'mode':'rules',**result}


def gemini_jam(learner_id):
    validate_ca_bundle()
    if not os.getenv('GEMINI_API_KEY'):raise RuntimeError('GEMINI_API_KEY is not configured')
    from google import genai
    from google.genai import types
    client=genai.Client(api_key=os.environ['GEMINI_API_KEY'])
    t=JamCoachTools(learner_id,source='gemini')
    declarations=[types.FunctionDeclaration(
        name='get_piano_jam_context',description="Review the current learner's recent played phrases and their features.",
        parameters_json_schema={'type':'object','properties':{},'required':[]}),
       types.FunctionDeclaration(name='set_piano_jam_direction',
        description='Choose one approved, open-ended next creative experiment. This is not scored.',
        parameters_json_schema={'type':'object','properties':{
            'direction_id':{'type':'string','enum':list(JAM_DIRECTIONS)},
            'reason':{'type':'string'}},'required':['direction_id','reason']})]
    tool=types.Tool(function_declarations=declarations)
    history=[types.Content(role='user',parts=[types.Part.from_text(
        text='The learner improvised on the virtual keyboard. CALL get_piano_jam_context, then '
             'CALL set_piano_jam_direction with a useful creative next step and a reason grounded '
             'in the notes played. Do not grade creativity or invent timing, emotion or fingering data.')])]
    system=('You are the CREATIVE JAM CAPABILITY of the SAME ToneTutor learning agent. '
            'Analyse only observable pitch/tap sequence features. Always use tools to act, '
            'respect user choice, choose one from the approved creative directions. '
            'Never invent a musical diagnosis or claim the system heard the user singing.')
    for _ in range(5):
        response=client.models.generate_content(
            model=os.getenv('GEMINI_MODEL','gemini-3.5-flash-lite'),contents=history,
            config=types.GenerateContentConfig(tools=[tool],system_instruction=system,temperature=.3,
                         automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)))
        calls=response.function_calls or []
        if not calls or not response.candidates:break
        history.append(response.candidates[0].content)
        parts=[]
        for call in calls[:4]:
            result=t.execute(call.name,{k:v for k,v in dict(call.args or {}).items() if v is not None})
            parts.append(types.Part.from_function_response(name=call.name,response={'result':result}))
        history.append(types.Content(role='user',parts=parts))
        if t.chosen:return {'mode':'gemini',**t.chosen}
    raise RuntimeError('Gemini did not select a creative direction')


def respond_to_jam(learner_id,notes,mode='rules'):
    features=describe_jam(notes)
    db.save_jam_phrase(learner_id,notes,features)
    if mode=='gemini':
        try:
            result=gemini_jam(learner_id)
            return {'features':features,**result}
        except Exception as exc:
            result=offline_jam(learner_id)
            return {'features':features,'warning':'Live Gemini unavailable; using offline rules. '+str(exc)[:180],**result}
    return {'features':features,**offline_jam(learner_id)}

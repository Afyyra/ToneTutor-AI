"""One learning agent with five responsibilities; execution is learner-scoped and logged.
Live mode: Gemini selects validated functions. Offline mode: explicitly rule-based controller.
"""
import os
from dotenv import load_dotenv
import database as db
from exercises import SKILLS,LEVELS
from tools import LearnerTools
from runtime_tls import validate_ca_bundle
from music import PITCH_CLASSES

load_dotenv()

SYSTEM = """You are ToneTutor, an autonomous music-learning planner for complete beginners.
You have five responsibilities: evaluate, plan, select exercises, control difficulty, and teach.
Use Python tools to ACT rather than only write recommendations.
For a normal learning cycle:
1) Call get_learning_profile, get_recent_attempts, and optionally get_note_confusions.
2) Compare performance by skill; give extra weight to recent repeated mistakes. Do not ignore unpractised foundational skills.
3) If note C is repeatedly confused with D, choose skill=notes, focus_note='C4', contrast_note='D4', and alternate focused comparisons.
4) Call update_learning_plan with a valid skill and difficulty, explaining briefly why.
5) Call assign_exercise with that same skill/difficulty. NEVER leave the learner without an assignment.
Only use existing tools; never invent grading results. Let Python grade answers. Avoid fixed sequential drills.
If the learner recently struggled, choose an easier level. If their last >=3 attempts in that skill are consistently correct, consider a harder level.
Avoid diagnosing health conditions or asserting absolute pitch can be acquired quickly.
The model CANNOT create calendar events. Scheduling tools only suggest slots; a user must confirm in the interface.
Do not send exercise answer keys or personal calendar event details.
"""

def offline_decision(learner_id, requested_skill=None, minutes_left=None, requested_type=None):
    """Transparent fallback controller. Not presented as AI; responds to error/confusion history."""
    t=LearnerTools(learner_id,source='rules')
    profile=t.execute('get_learning_profile')
    recent=t.execute('get_recent_attempts',{'limit':20})['attempts']
    confusions=t.execute('get_note_confusions')['notes']
    recent_note_attempts=[r for r in recent if r['skill']=='notes'][:12]
    recent_pair_counts={}
    for attempt in recent_note_attempts:
        target=attempt.get('target_note')
        selected=attempt.get('submitted')
        if target and isinstance(selected,str) and not attempt['correct']:
            pair=(target,selected)
            recent_pair_counts[pair]=recent_pair_counts.get(pair,0)+1
    # Stop drilling a confused note after three consecutive recent successes on it.
    recovered=set()
    for note in [r.get('target_note') for r in recent_note_attempts]:
        candidates=[r for r in recent_note_attempts if r.get('target_note')==note][:3]
        if len(candidates)==3 and all(r['correct'] for r in candidates):recovered.add(note)
    if requested_skill in SKILLS:skill=requested_skill
    else:
        # Priority for repeated confusion (at least 2 mistakes on one pair).
        pairs=[(count,target[:-1],wrong[:-1]) for (target,wrong),count in recent_pair_counts.items()
               if count>=2 and target not in recovered]
        if pairs:skill='notes'
        else:
            # Where seen, favour weaker skills; otherwise rotate over major foundations.
            primary=['pitch','notes','notation','intervals','melody','theory','rhythm','piano']
            def rank(s):
                d=profile['skills'][s]
                base=55 if not d['attempts'] else d['accuracy']
                recent_streak=sum(1 for r in recent[:4] if r['skill']==s)
                # Rotate after substantial repetition rather than asking one weak topic indefinitely.
                if len(recent)>=4 and all(r['skill']==s for r in recent[:4]):base+=38
                return (base,-d['attempts'],primary.index(s))
            skill=min(primary,key=rank)
    own=[row for row in recent if row['skill']==skill][:5]
    current=(profile['plan'] or {}).get('difficulty','easy') if (profile['plan'] or {}).get('skill')==skill else 'easy'
    ix=LEVELS.index(current)
    if len(own)>=3 and all(r['correct'] for r in own[:3]): ix=min(2,ix+1)
    elif len(own)>=2 and all(not r['correct'] for r in own[:2]):ix=max(0,ix-1)
    difficulty=LEVELS[ix]
    focus=None;contrast=None
    if skill=='notes':
        pairs=sorted(((count,a[:-1],b[:-1]) for (a,b),count in recent_pair_counts.items()
                      if a not in recovered),reverse=True)
        if pairs and pairs[0][0]>=2:
            _,a,b=pairs[0]
            focus=a+'4';contrast=b+'4'
        else:
            attempts=profile['notes']
            candidates=[p for p in PITCH_CLASSES if (difficulty!='easy' or p in ('C','D','E','F','G'))]
            focus=min(candidates,key=lambda p:(attempts[p]['correct']/max(1,attempts[p]['attempts']),attempts[p]['attempts']))+'4'
    reason=f'Practice {skill}: recent performance and note-confusion history suggest {difficulty} exercises.'
    if focus:reason+=f' Focus on {focus}'+(f' versus {contrast}.' if contrast else '.')
    t.execute('update_learning_plan',{'skill':skill,'difficulty':difficulty,'reason':reason,
                                      'focus_note':focus,'contrast_note':contrast})
    if skill in ('notes','pitch') and own[:2] and all(not r['correct'] for r in own[:2]):
        t.execute('provide_learning_support',{'skill':skill,'kind':'hint'})
    assignment=t.execute('assign_exercise',{'skill':skill,'difficulty':difficulty,
                                             **({'exercise_type':requested_type} if requested_type else {})})
    return {'mode':'rules','decision':reason,'assignment':assignment}

# Explicit schemas avoid inadvertently exposing learner_id or changing calendar events.
def declarations(types):
    def fn(name,description,properties=None,required=None):
        return types.FunctionDeclaration(name=name,description=description,
            parameters_json_schema={'type':'object','properties':properties or {},'required':required or []})
    en=lambda values: {'type':'string','enum':list(values)}
    return [
        fn('get_learning_profile','Read summary skill performance, learning plan, goals and note confusion data.'),
        fn('get_recent_attempts','Read last N graded attempts.',{'limit':{'type':'integer','minimum':1,'maximum':30}}),
        fn('get_note_confusions','Read individual note accuracy and mistakes between note pairs.'),
        fn('get_available_lessons','Find available lesson titles and skills.'),
        fn('update_learning_plan','Save chosen skill, difficulty and reason before assignment.',
           {'skill':en(SKILLS),'difficulty':en(LEVELS),'reason':{'type':'string'},
            'focus_note':{'type':'string'},'contrast_note':{'type':'string'}},
           ['skill','difficulty','reason']),
        fn('assign_exercise','Generate and assign a fresh exercise matching the saved plan.',
           {'skill':en(SKILLS),'difficulty':en(LEVELS),
            'exercise_type':{'type':'string'}},['skill','difficulty']),
        fn('provide_learning_support','Record a helpful beginner hint or explanation.',
           {'skill':en(SKILLS),'kind':en(['hint','explanation'])},['skill']),
        fn('suggest_training_slots','Only when learner requests scheduling: retrieve free slots; does not create events.',
           {'days':{'type':'integer','minimum':1,'maximum':7}}),
    ]

def gemini_decision(learner_id,requested_skill=None,minutes_left=None,requested_type=None):
    validate_ca_bundle()
    if not os.getenv('GEMINI_API_KEY'):raise RuntimeError('GEMINI_API_KEY is not configured')
    from google import genai
    from google.genai import types
    model=os.getenv('GEMINI_MODEL','gemini-3.5-flash-lite')
    t=LearnerTools(learner_id,source='gemini')
    client=genai.Client(api_key=os.environ['GEMINI_API_KEY'])
    tool=types.Tool(function_declarations=declarations(types))
    instruction=(f'Select the NEXT learning activity for learner ID {learner_id!r}. '
                 f'The user requested skill {requested_skill!r} and exercise type {requested_type!r}; honour both when valid. '
                 f'Time remaining today approx {minutes_left if minutes_left is not None else "unknown"} minutes. '
                 'First examine profile and attempts, then update plan and assign an exercise. '
                 'Choose a mix of skills over multiple sessions. Do not merely write advice.')
    history=[types.Content(role='user',parts=[types.Part.from_text(text=instruction)])]
    call_count=0;last_text=''
    for _ in range(7):
        response=client.models.generate_content(
            model=model,contents=history,
            config=types.GenerateContentConfig(system_instruction=SYSTEM,tools=[tool],temperature=0.3,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)))
        calls=response.function_calls or []
        if not calls:
            last_text=(response.text or '').strip();break
        if not response.candidates:break
        history.append(response.candidates[0].content) # preserves Gemini thought signatures
        results=[]
        for call in calls:
            call_count+=1
            if call_count>18:raise RuntimeError('Agent exceeded the permitted tool-call budget')
            args=dict(call.args or {})
            # Remove null tool properties (they should be omitted, not passed as None for optional args)
            args={k:v for k,v in args.items() if v is not None}
            outcome=t.execute(call.name,args)
            results.append(types.Part.from_function_response(name=call.name,response={'result':outcome}))
        history.append(types.Content(role='user',parts=results))
        if db.active(learner_id):
            last_text='The agent updated the learning plan and assigned an exercise.'
            break
    if not db.active(learner_id):raise RuntimeError('Agent did not assign an exercise within tool limit')
    return {'mode':'gemini','decision':last_text or (db.get_plan(learner_id) or {}).get('reason',''),
            'tool_calls':call_count}

def next_activity(learner_id,mode='rules',requested_skill=None,minutes_left=None,requested_type=None):
    if db.active(learner_id):return {'mode':'existing','decision':'Continue your active exercise.'}
    if mode=='gemini':
        try:return gemini_decision(learner_id,requested_skill,minutes_left,requested_type)
        except Exception as e:
            if db.active(learner_id):
                return {'mode':'gemini_partial',
                        'decision':(db.get_plan(learner_id) or {}).get('reason', 'A Gemini tool assigned the current exercise.'),
                        'warning':'Gemini had an error after creating an assignment: '+str(e)[:180]}
            fallback=offline_decision(learner_id,requested_skill,minutes_left,requested_type)
            fallback['fallback_reason']=str(e)[:250]
            return fallback
    return offline_decision(learner_id,requested_skill,minutes_left,requested_type)


def calendar_recommendation(learner_id,mode='rules'):
    """Optional calendar agent: searches availability, chooses a proposed slot, never writes Google Calendar."""
    t=LearnerTools(learner_id,source='gemini' if mode=='gemini' else 'rules')
    if mode=='gemini' and os.getenv('GEMINI_API_KEY'):
        try:
            validate_ca_bundle()
            from google import genai
            from google.genai import types
            client=genai.Client(api_key=os.environ['GEMINI_API_KEY'])
            fns=[d for d in declarations(types) if d.name in ('get_learning_profile','suggest_training_slots')]
            fns.append(types.FunctionDeclaration(
                name='select_training_slot',description='Select an available candidate by index and explain why. Does NOT create events.',
                parameters_json_schema={'type':'object','properties':{'index':{'type':'integer'},'reason':{'type':'string'}},
                                        'required':['index','reason']}))
            tool=types.Tool(function_declarations=fns)
            history=[types.Content(role='user',parts=[types.Part.from_text(text=(
               'A learner requested smart training scheduling. Read profile, find free/busy availability, '
               'then SELECT one available slot that fits their daily time goal and preferred reminder time. '
               'You must call select_training_slot with the exact index, and stop. Do not create any calendar event.'))])]
            for _ in range(6):
                r=client.models.generate_content(model=os.getenv('GEMINI_MODEL','gemini-3.5-flash-lite'),
                    contents=history,config=types.GenerateContentConfig(
                        tools=[tool],system_instruction=SYSTEM,
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)))
                if not r.function_calls:break
                history.append(r.candidates[0].content)
                parts=[]
                for fc in r.function_calls:
                    value=t.execute(fc.name,dict(fc.args or {}))
                    parts.append(types.Part.from_function_response(name=fc.name,response={'result':value}))
                history.append(types.Content(role='user',parts=parts))
                if t._chosen:return {'mode':'gemini',**t._chosen,'slots':t._slots}
        except Exception as exc:
            fallback_error=str(exc)[:180]
        else:fallback_error='Gemini did not select a valid slot.'
    else:fallback_error='Offline scheduling recommendation.'
    slots=t.execute('suggest_training_slots',{'days':7})
    if slots.get('error'):return {'error':slots['error']}
    if not slots['slots']:return {'error':'No available practice slots in the selected window.'}
    chosen=t.execute('select_training_slot',{'index':0,'reason':'Closest free slot to preferred time on the earliest available day.'})
    return {'mode':'rules','reason':fallback_error,**chosen,'slots':t._slots}

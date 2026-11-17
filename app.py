"""ToneTutor AI Enhanced — local educational prototype.
Run: streamlit run app.py
"""
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo
import streamlit as st
from dotenv import load_dotenv

import audio
import database as db
import scheduler
from agent import next_activity
from exercises import SKILLS, LEVELS, generate
from music import LESSONS, LESSON_BY_ID, PITCH_CLASSES, ALL_KEYS, note_info, scale, chord
from notation import staff_svg, rhythm_svg
from piano_widget import render_piano, render_piano_event
from piano_coach import GOALS, next_piano_mission, public_mission, process_piano_press, respond_to_jam
from browser_webcam import browser_webcam_piano

load_dotenv()
st.set_page_config(page_title='ToneTutor AI | DEMO',page_icon='🎹',layout='wide')
db.initialize()
st.markdown('''<style>
  .tt-demo {position:fixed;top:12px;right:14px;z-index:999999;
    padding:5px 12px;background:#a3273c;color:white;font-weight:750;letter-spacing:.13em;
    border-radius:7px;box-shadow:0 2px 10px #0003}
  .block-container {padding-top:2.7rem}
  [data-testid="stMetricValue"] {font-size:1.65rem}
</style><div class="tt-demo">DEMO</div>''',unsafe_allow_html=True)

if 'learner' not in st.session_state: st.session_state.learner='DEMO-001'
if 'page' not in st.session_state: st.session_state.page='Dashboard'
if 'feedback' not in st.session_state: st.session_state.feedback=None
if 'piano_steps' not in st.session_state: st.session_state.piano_steps=[]
if 'practice_active' not in st.session_state: st.session_state.practice_active=False
if 'practice_tick' not in st.session_state: st.session_state.practice_tick=time.time()


def minutes_remaining(learner):
    goal=db.preferences(learner)['goal_minutes']
    today=db.daily_times(learner,1)[0]['minutes']
    return max(0,round(goal-today,1))


def tick_practice():
    if st.session_state.practice_active:
        now=time.time()
        elapsed=max(0,min(3600,int(now-st.session_state.practice_tick)))
        if elapsed:db.add_seconds(st.session_state.learner,elapsed)
        st.session_state.practice_tick=now


def set_page(name):
    st.session_state.page=name
    st.session_state.feedback=None
    st.session_state.piano_steps=[]
    st.rerun()


def ensure_assessment(learner):
    if db.get_profile(learner)['assessment_complete']:return False
    ids=[r for r in db.recent_attempts(learner,200) if r['assessment']]
    skills=['pitch','notes','theory','intervals','notation','rhythm']
    if len(ids)>=len(skills):
        db.mark_assessment_done(learner)
        return False
    if not db.active(learner):
        db.assign(learner,generate(skills[len(ids)],'easy'))
    return True


def display_audio(ex,show_solution=False):
    notes=ex['notes']
    if ex['type']=='compare_pitch':
        a,b=st.columns(2)
        with a:st.write('**Sound A**');st.audio(audio.wav_bytes(notes[0]))
        with b:st.write('**Sound B**');st.audio(audio.wav_bytes(notes[1]))
    elif notes and ex['type']!='staff_note' and ex['type']!='piano_follow':
        st.audio(audio.wav_bytes(notes),format='audio/wav')
        if ex['type'] in ('identify_note','contrast_notes'):
            with st.expander('Reference notes — listen before answering'):
                for note in ex['options']:
                    st.caption(note);st.audio(audio.wav_bytes(note,note_seconds=.32),format='audio/wav')
    if ex['type']=='staff_note':
        st.image(staff_svg(notes[0],ex['meta'].get('clef','treble'),show_solution))


def render_question(learner,assessment=False):
    ex=db.active(learner)
    if not ex:
        st.info('No active question. Select a lesson or ask the tutor to choose the next activity.')
        return
    st.caption(f"{ex['skill'].title()} · {ex['difficulty'].title()} · {ex['type'].replace('_',' ').title()}")
    st.subheader(ex['question'])
    if ex['type']=='piano_follow':
        st.info('Play the displayed notes on the virtual keyboard in order. You can clear and replay your sequence.')
        st.write(' → '.join(ex['notes']))
    display_audio(ex)
    if ex['type'] in ('melody_repeat','piano_follow','piano_note'):
        if st.session_state.get('last_exercise_id')!=ex['id']:
            st.session_state.piano_steps=[]
            st.session_state.last_exercise_id=ex['id']

        pressed=render_piano(key='exercise-piano-'+ex['id'],hide_labels=(ex['type']=='melody_repeat'))
        if pressed in ALL_KEYS and len(st.session_state.piano_steps)<12:
            st.session_state.piano_steps.append(pressed)
        if st.session_state.get('exercise_input')==INPUT_BROWSER:
            st.caption('📷 Webcam in browser: tap the notes on your table. They are added to your answer below.')
            # No target highlight here: that would reveal the answer.
            tapped=browser_webcam_piano('bw-training',sensitivity=st.session_state.get('bw_sensitivity','normal'),
                                        hide_labels=(ex['type']=='melody_repeat'))
            room=max(0,12-len(st.session_state.piano_steps))
            st.session_state.piano_steps.extend(tapped[:room])
            piano_answer(learner,ex,assessment)
        else:
            piano_answer(learner,ex,assessment)
        return
    selected=st.radio('Your answer',ex['options'],index=None,key='answer-'+ex['id'])
    if st.button('Submit answer',type='primary',key='submit-'+ex['id'],disabled=not bool(selected)):
        submit_answer(learner,ex,selected,assessment)


def submit_answer(learner,ex,selected,assessment):
    try:
        tick_practice()
        result=db.submit(learner,selected,assessment=assessment)
        st.session_state.feedback={'result':result,'skill':ex['skill'],'exercise_id':ex['id'],
                                   'notes':ex['notes'],'submitted':selected}
        st.rerun()
    except Exception as exc:st.error(str(exc))


def piano_answer(learner,ex,assessment):
    """Played sequence, clear and submit for piano exercises."""
    st.caption('Played: '+(' → '.join(st.session_state.piano_steps) or 'nothing yet'))
    if st.button('Clear played sequence',key='clear-'+ex['id']):
        st.session_state.piano_steps=[]
        st.rerun()
    selected=list(st.session_state.piano_steps)
    if st.button('Submit answer',type='primary',key='submit-'+ex['id'],disabled=not bool(selected)):
        submit_answer(learner,ex,selected,assessment)

def show_feedback(learner,is_assessment=False):
    fb=st.session_state.feedback
    if not fb:return False
    result=fb['result']
    if result['correct']:st.success('Correct! Well done.')
    else:st.warning('Not quite. You can learn from this answer.')
    st.write(result['explanation'])
    if 'by_note' in result:
        st.write('Expected: '+' → '.join(result['correct_answer']))
        st.write(f"Correct positions: {result['partial']}/{result['total']}")
        if fb['submitted']:
            st.write('Your notes: '+' → '.join(fb['submitted']))
    else:
        st.write('Correct answer: **'+str(result['correct_answer'])+'**')
    if st.button('Continue learning',type='primary',key='continue-after-answer'):
        st.session_state.feedback=None
        st.session_state.piano_steps=[]
        if is_assessment:
            if not ensure_assessment(learner):
                set_page('Training')
        else:
            focus=None
            st.session_state.pending_skill=focus
            st.session_state.trigger_agent=True
        st.rerun()
    return True


def show_dashboard(learner):
    profile=db.get_profile(learner);prefs=profile['preferences']
    st.title('🎹 ToneTutor AI')
    st.markdown('**Train your ears. Understand your music.**')
    now=datetime.now(ZoneInfo(prefs['timezone']))
    remaining=minutes_remaining(learner)
    if now.strftime('%H:%M')>=prefs['reminder_time'] and remaining>0:
        st.info(f"🎵 In-app reminder: your {prefs['goal_minutes']}-minute daily practice goal is still open. No pressure — even a short session helps.")
    c1,c2,c3=st.columns(3)
    c1.metric('Daily goal',f"{prefs['goal_minutes']} min")
    c2.metric('Practised today',f"{db.daily_times(learner,1)[0]['minutes']} min")
    c3.metric('Still to go',f'{remaining} min')
    st.progress(min(1,db.daily_times(learner,1)[0]['minutes']/prefs['goal_minutes']))
    plan=profile['plan']
    st.markdown('### Your adaptive learning path')
    if plan:st.info(f"**Next focus: {plan['skill'].title()} ({plan['difficulty']})** — {plan['reason']}")
    else:st.write('Complete a short assessment so the tutor can build your first learning plan.')
    latest=db.recent_attempts(learner,3)
    if latest:
        st.markdown('#### Previous session recap')
        st.write(f"You last practised **{latest[0]['skill']}**. Recent results: "+', '.join(('✓' if r['correct'] else '✗')+' '+r['skill'] for r in latest))
    a,b,c=st.columns(3)
    with a:
        if st.button('Start / Continue Training',use_container_width=True,type='primary'):set_page('Training')
    with b:
        if st.button('Explore Lessons',use_container_width=True):set_page('Lessons')
    with c:
        if st.button('Play the Piano',use_container_width=True):set_page('Piano')
    st.markdown('#### Your skill progress')
    cols=st.columns(4)
    for i,(name,s) in enumerate(profile['skills'].items()):
        cols[i%4].metric(name.title(),f"{s['accuracy']}%" if s['accuracy'] is not None else 'Not tested')


def show_lessons(learner):
    st.title('📚 Music Learning Library')
    st.write('Explore ten beginner-friendly lessons. Listen to real pitches and practice afterwards.')
    topics={x['title']:x['id'] for x in LESSONS}
    selection=st.selectbox('Choose a topic',list(topics))
    lesson=LESSON_BY_ID[topics[selection]]
    st.caption(lesson['level']+' · '+lesson['skill'].title())
    st.markdown(lesson['text']);st.markdown('**Listen and notice:** '+lesson['example'])
    if lesson['audio']:st.audio(audio.wav_bytes(lesson['audio'],note_seconds=.45),format='audio/wav')
    if lesson['id']=='alphabet':
        cols=st.columns(4)
        for i,pc in enumerate(PITCH_CLASSES):
            with cols[i%4]:
                note=pc+'4';st.write('**'+pc+'**');st.audio(audio.wav_bytes(note,note_seconds=.32))
    if lesson['id']=='scales':
        st.caption('C major: '+' – '.join(scale('C4')))
        st.caption('A natural minor: '+' – '.join(scale('A4',minor=True)))
    if lesson['id']=='chords':
        st.caption('C major triad: '+' + '.join(chord('C4','major')))
    if lesson['id']=='notation':
        st.image(staff_svg('E4','treble',show_name=True))
        st.image(rhythm_svg())
    if lesson['id']=='rhythm':
        st.caption('Listen to 4/4 at 100 BPM, then 3/4 at 90 BPM. The first beat of each bar has a higher click.')
        st.audio(audio.metronome(100,8,4),format='audio/wav')
        st.audio(audio.metronome(90,9,3),format='audio/wav')
    if st.button('Mark lesson as studied'):
        db.complete_lesson(learner,lesson['id']);st.success('Lesson saved.')
    if st.button('Practise this topic with the tutor',type='primary'):
        if not db.get_profile(learner)['assessment_complete']:
            st.warning('Complete the quick initial assessment first.');return
        if db.active(learner):
            st.info('Finish your current question before changing topic.')
        else:
            st.session_state.pending_skill=lesson['skill'];set_page('Training')


def show_training(learner,mode):
    st.title('🎧 Adaptive Ear Training & Practice')
    if not db.get_profile(learner)['assessment_complete']:
        st.info('First, complete six short assessment questions. You may replay sounds as often as needed.')
        if st.session_state.feedback:
            show_feedback(learner,is_assessment=True)
        else:
            ensure_assessment(learner)
            count=sum(bool(r['assessment']) for r in db.recent_attempts(learner,200))
            st.progress(min(1,count/6),text=f'Assessment: {count}/6 completed')
            render_question(learner,assessment=True)
        return
    st.caption(f'Tutor mode: {"Gemini AI function calling" if mode=="gemini" else "Rules-based demonstration (not AI)"}')
    with st.expander('Practice timer and daily goal',expanded=True):
        c1,c2=st.columns(2)
        with c1:
            if not st.session_state.practice_active:
                if st.button('▶ Start tracking practice time'):
                    st.session_state.practice_active=True;st.session_state.practice_tick=time.time();st.rerun()
            else:
                if st.button('■ Stop tracking'):
                    tick_practice();st.session_state.practice_active=False;st.rerun()
        with c2:st.metric('Daily time remaining',f'{minutes_remaining(learner)} minutes')
        st.caption('Time is saved during interactions and when you stop the timer. It is approximate, not an always-running background timer.')
    if st.session_state.feedback:
        show_feedback(learner)
        return
    if st.session_state.get('trigger_agent'):
        st.session_state.trigger_agent=False
        with st.spinner('Tutor is choosing the next activity...'):
            output=next_activity(learner,mode,minutes_left=minutes_remaining(learner))
        st.session_state.agent_message=output
    ex=db.active(learner)
    if not ex:
        requested=st.session_state.pop('pending_skill',None)
        if st.button('Let the tutor choose my next exercise',type='primary'):
            with st.spinner('Evaluating performance and planning...'):
                output=next_activity(learner,mode,requested_skill=requested,
                                     minutes_left=minutes_remaining(learner))
            st.session_state.agent_message=output
            st.rerun()
        elif requested:
            # Preserve user request across reruns until the button is pressed.
            st.session_state.pending_skill=requested
        return
    message=st.session_state.get('agent_message')
    if message:
        st.info('Tutor decision: '+str(message.get('decision','Next learning activity selected.')))
        if message.get('fallback_reason'):
            st.warning('Live AI unavailable; used offline rules instead. '+message['fallback_reason'])
        if message.get('warning'):
            st.warning(message['warning'])
    render_question(learner)
    support=db.latest_support(learner)
    if support:
        with st.expander('Tutor guidance'):st.write(support)


INPUT_SCREEN='On-screen piano'
INPUT_BROWSER='Webcam in browser (works online)'
INPUT_OPTIONS=[INPUT_SCREEN,INPUT_BROWSER]
INPUT_HELP='Webcam in browser runs the camera and hand tracking in your own browser, so it also works on the online app.'


def show_piano_jam(learner, use_browser_webcam=False):
    """Open-ended exploration: the agent responds to what was played, without scoring creativity."""
    st.subheader('🎶 Creative Jam · Agent-Guided Exploration')
    st.caption('Play an original phrase freely. ToneTutor observes which keys you tapped, '
               'then selects a creative next step. There is no right or wrong answer.')
    if st.session_state.get('jam_owner')!=learner:
        st.session_state.jam_owner=learner
        st.session_state.jam_notes=[]
        st.session_state.jam_last_event=None
        st.session_state.jam_advice=None
    st.info('The browser provides audio; only the keys you play are recorded. '
            'The agent cannot detect hand position, timing, microphone sound or emotion.')
    if use_browser_webcam:
        tapped=browser_webcam_piano('bw-coach',sensitivity=st.session_state.get('bw_sensitivity','normal'))
        room=max(0,20-len(st.session_state.jam_notes))
        st.session_state.jam_notes=[*st.session_state.jam_notes,*tapped[:room]]
        event=None
    else:
        event=render_piano_event(key='jam-piano-'+learner)
    if event and event['id']!=st.session_state.jam_last_event:
        st.session_state.jam_last_event=event['id']
        if event['note'] in ALL_KEYS and len(st.session_state.jam_notes)<20:
            st.session_state.jam_notes=[*st.session_state.jam_notes,event['note']]
            st.rerun()
    notes=st.session_state.jam_notes
    st.write('**Your phrase ('+str(len(notes))+'/20 keys):** '+(' → '.join(notes) or 'Play a few keys to start.'))
    if notes:st.audio(audio.wav_bytes(notes[-16:],note_seconds=.27),format='audio/wav')
    a,b=st.columns(2)
    with a:
        if st.button('Ask the coach to respond to my phrase',type='primary',disabled=len(notes)<3):
            with st.spinner('Reviewing the played-key pattern...'):
                st.session_state.jam_advice=respond_to_jam(learner,notes,st.session_state.tutor_mode)
            st.session_state.jam_notes=[]
            st.rerun()
    with b:
        if st.button('Start another original phrase'):
            st.session_state.jam_notes=[]
            st.session_state.jam_advice=None
            st.rerun()
    result=st.session_state.jam_advice
    if result:
        if result.get('warning'):st.warning(result['warning'])
        st.success('**Creative direction: '+result['title']+'**')
        st.write(result['prompt'])
        st.write('**Why this direction:** '+result['reason'])
        f=result['features']
        st.caption(f"Observed {f['notes_played']} keys, {f['unique_notes']} distinct notes, "
                   f"{f['ascending_steps']} rises, {f['descending_steps']} falls, "
                   f"and {f['large_leaps']} larger jumps. This is descriptive—not a creativity grade.")
        st.caption('Open Progress to verify get_piano_jam_context and '
                   'set_piano_jam_direction in the tool log.')


def show_piano_coach(learner):
    """Hands-on piano guidance: observe key taps, react, and adapt the next mission."""
    st.subheader('🤖 AI Piano Coach · Guided Keyboard Studio')
    st.caption('Play real notes on the virtual keyboard. The coach tracks every tap, '
               'responds immediately, and plans the next mission from your recorded accuracy.')
    studio=st.radio('Piano coaching studio', ['Guided Missions','Creative Jam'],horizontal=True,
                    key='coach_studio')
    input_method=st.radio('How will you play?',INPUT_OPTIONS,horizontal=True,key='coach_input_method',
                          help=INPUT_HELP)
    use_browser=input_method==INPUT_BROWSER
    if use_browser:
        st.selectbox('Tap sensitivity',['normal','high','low'],key='bw_sensitivity')
    if studio=='Creative Jam':
        show_piano_jam(learner,use_browser)
        return
    mode=st.session_state.tutor_mode
    st.info('Controller selected: **'+('Gemini AI' if mode=='gemini' else 'Offline rules (not AI)')+
            '**. Gemini selects the next practical mission through logged Python tools; '
            'Python verifies key presses. No microphone, fingering, or rhythm detection.')
    goal=st.selectbox('What would you like to practise?',GOALS,key='piano_coach_goal')

    if st.session_state.get('coach_owner')!=learner:
        st.session_state.coach_owner=learner
        st.session_state.coach_outcome=None
        st.session_state.coach_session_token=None

    mission=db.coach_active(learner)
    if not mission:
        if st.session_state.get('coach_outcome'):
            outcome=st.session_state.coach_outcome
            st.success('Mission complete! You played all the requested notes.')
            a,b,c=st.columns(3)
            a.metric('Correct notes',outcome['notes_completed'])
            b.metric('Extra / incorrect taps',outcome['mistakes'])
            c.metric('Note accuracy',f"{outcome['accuracy']:.0%}")
            if outcome['accuracy']<0.8:
                st.info('Your next mission may reinforce the same area at a gentler difficulty.')
            else:
                st.info('Your coach can now decide whether to vary the pattern or increase the challenge.')
        if st.button('🎯 Ask coach to plan my next keyboard mission',type='primary'):
            with st.spinner('Analysing keyboard progress and selecting a practical mission...'):
                result=next_piano_mission(learner,mode,goal)
            st.session_state.coach_controller=result['mode']
            st.session_state.coach_warning=result.get('warning')
            st.session_state.coach_outcome=None
            st.rerun()
        history=db.coach_history(learner,5)
        if history:
            st.markdown('#### Your recent piano missions')
            st.dataframe([{'mission':h['drill_id'].replace('_',' ').title(),
                           'skill':h['goal'],'difficulty':h['difficulty'],
                           'note_accuracy':f"{h['accuracy']:.0%}",
                           'mistakes':h['mistakes']} for h in history],
                         hide_index=True,use_container_width=True)
        return

    data=public_mission(mission)
    token=(learner,data['id'])
    if st.session_state.get('coach_session_token')!=token:
        st.session_state.coach_session_token=token
        st.session_state.coach_events=[]
        st.session_state.coach_last_event=None
        st.session_state.coach_feedback=''
    events=st.session_state.coach_events
    done=sum(1 for item in events if item['correct'])
    expected=data['notes']
    st.markdown('### '+data['title'])
    st.write('**Coach decision:** '+data['reason'])
    st.caption(f"Focus: {data['goal']} · Difficulty: {data['difficulty'].title()}")
    st.progress(done/len(expected),text=f'Correct keys in sequence: {done}/{len(expected)}')
    st.markdown('**Play this original short note pattern in order:**')
    st.write(' → '.join('**['+n+']**' if i==done else n for i,n in enumerate(expected)))
    st.audio(audio.wav_bytes(expected,note_seconds=.33),format='audio/wav')
    st.caption('Reference sound above. Listen, then play the highlighted next key. '
               'Wrong taps are counted but do not move you forward.')
    st.info('💡 '+data['tip'])

    # Both inputs produce note names; Python checks every one the same way.
    if use_browser:
        played=browser_webcam_piano('bw-coach',target=expected[done],
                                    sensitivity=st.session_state.get('bw_sensitivity','normal'))
    else:
        played=[]
        event=render_piano_event(key='coach-piano-'+str(data['id']),target=expected[done])
        if event and event['id']!=st.session_state.coach_last_event:
            st.session_state.coach_last_event=event['id']
            played=[event['note']]
    played=[note for note in played if note in ALL_KEYS]
    if played:
        try:
            for note in played:
                action=process_piano_press(expected,note,st.session_state.coach_events)
                st.session_state.coach_events=action['history']
                st.session_state.coach_feedback=action['message']
                if action['finished']:
                    tick_practice()
                    result=db.complete_coach_mission(learner,data['id'],
                                                      [tap['note'] for tap in action['history']],
                                                      input_source='browser_webcam' if use_browser else 'on_screen')
                    st.session_state.coach_outcome=result
                    st.session_state.coach_session_token=None
                    break
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    if st.session_state.coach_feedback:
        if st.session_state.coach_feedback.startswith('Correct'):
            st.success(st.session_state.coach_feedback)
        else:
            st.warning(st.session_state.coach_feedback)
    if events:
        st.caption('Your taps: '+' → '.join(('✓' if tap['correct'] else '✗')+' '+tap['note'] for tap in events))
    if st.session_state.get('coach_warning'):
        st.warning(st.session_state.coach_warning)
    st.caption('For judge verification: open Progress → Actual tool execution log. '
               'Look for get_piano_coach_context and set_piano_coach_mission; source=gemini means real tool calls.')
    if st.button('Cancel this mission (no score saved)'):
        db.cancel_coach_mission(learner)
        st.session_state.coach_session_token=None
        st.session_state.coach_outcome=None
        st.rerun()

def show_piano(learner):
    st.title('🎹 Interactive Virtual Piano')
    st.caption('24 playable keys: C4 to B5, including all black keys. Sound plays immediately when clicked.')
    mode=st.radio('Practice mode',
                  ['AI Piano Coach','Free Play','Learn the Notes'],
                  horizontal=True)
    if mode=='AI Piano Coach':
        show_piano_coach(learner)
        return
    input_method=st.radio('How will you play?',INPUT_OPTIONS,horizontal=True,key='piano_input_method',
                          help=INPUT_HELP)
    # Remembered outside the widget so the Training page knows which input to offer for piano exercises.
    st.session_state.exercise_input=input_method

    if mode=='Learn the Notes':
        selected=st.selectbox('Explore a note',list(ALL_KEYS),key='learn_note')
        info=note_info(selected)
        st.write(f"**{selected}** · {info['frequency_hz']} Hz · {info['key_type']} key · Enharmonic spelling: {info['enharmonic']}")
        pressed=render_piano(key='free-piano',target=selected)
    else:
        pressed=render_piano(key='free-piano')
    if pressed:st.success('You played '+pressed)
    st.caption('Free play and guided challenges are available. The AI Piano Coach observes played keys and plans the next keyboard mission.')
    # Rendered last so Learn the Notes compares taps with the note chosen above.
    if input_method==INPUT_BROWSER:
        st.divider()
        show_browser_webcam(learner,mode)


def show_browser_webcam(learner, piano_mode):
    """Webcam piano that runs in the learner's browser (works on the hosted app too)."""
    st.subheader('📷 Webcam piano · runs in your browser')
    st.caption('Camera, hand tracking and tap detection run inside your browser, so this also works on the '
               'online app. Only the note names you play are sent to ToneTutor; video never leaves your device.')
    sensitivity=st.selectbox('Tap sensitivity',['normal','high','low'],key='bw_sensitivity')
    target=st.session_state.get('learn_note') if piano_mode=='Learn the Notes' else None
    tapped=browser_webcam_piano('bw-piano',target=target,sensitivity=sensitivity)
    if tapped:
        st.session_state.bw_recent=[*st.session_state.get('bw_recent',[]),*tapped][-10:]
    recent=st.session_state.get('bw_recent',[])
    if piano_mode=='Learn the Notes':
        if tapped:
            if tapped[-1]==target:st.success('✅ '+target+' — that is the correct key.')
            else:st.warning('You played '+tapped[-1]+'. The selected note is '+str(target)+'.')
        else:
            st.info('Tap **'+str(target)+'** on the keyboard drawn over your table.')
    st.caption('📷 Recent webcam taps: '+(' → '.join(recent) if recent else 'none yet'))


def show_notation(learner):
    st.title('🎼 Music Notation & Staff Reading')
    st.write('Learn the five-line staff, treble and bass clefs, ledger lines and note positions.')
    clef=st.selectbox('Clef',['treble','bass'])
    note=st.selectbox('Choose a staff note',(['C4','D4','E4','F4','G4','A4','B4','C5','D5','E5','F5'] if clef=='treble' else ['C3','D3','E3','F3','G3','A3','B3','C4','D4']))
    st.image(staff_svg(note,clef,show_name=True))
    st.write('Listen to the note and find it on the virtual keyboard when it falls in the C4–B5 range.')
    st.audio(audio.wav_bytes(note),format='audio/wav')
    st.image(rhythm_svg())
    st.markdown('''**Staff facts:** Treble lines E–G–B–D–F (bottom up), spaces F–A–C–E. Bass lines G–B–D–F–A and spaces A–C–E–G. Ledger lines extend the staff. Whole, half, quarter and eighth notes represent different rhythmic durations; rests mark silence.''')
    if st.button('Practise identifying staff notes',type='primary'):
        st.session_state.pending_skill='notation';set_page('Training')


def show_progress(learner):
    st.title('📊 Progress & Learning Continuity')
    profile=db.get_profile(learner)
    scores=[{'skill':name,'accuracy':info['accuracy'] or 0,'attempts':info['attempts']} for name,info in profile['skills'].items()]
    st.subheader('Performance by skill')
    st.bar_chart(scores,x='skill',y='accuracy')
    st.subheader('Daily practice minutes (last 14 days)')
    st.bar_chart(db.daily_times(learner,14),x='day',y='minutes')
    st.subheader('Individual note recognition')
    note_rows=[{'note':k,'accuracy':round(100*v['correct']/v['attempts']) if v['attempts'] else None,
                'attempts':v['attempts'], 'common_confusion':max(v['confused_with'],key=v['confused_with'].get) if v['confused_with'] else '—'}
               for k,v in profile['notes'].items()]
    st.dataframe(note_rows,hide_index=True,use_container_width=True)
    done=db.completed_lessons(learner)
    st.info(f'Lessons studied: {len(done)} / {len(LESSONS)}')
    st.subheader('Current learning plan')
    st.json(profile['plan'] or {'message':'Not assigned yet.'})
    st.subheader('Recent attempts')
    attempts=db.recent_attempts(learner,15)
    if attempts:st.dataframe([{'skill':r['skill'],'difficulty':r['difficulty'],'correct':bool(r['correct']),
                               'target_note':r['note_target'],'submitted':str(r['submitted'])} for r in attempts],hide_index=True)
    st.subheader('AI Piano Coach · recent played-key accuracy')
    coach_rows=db.coach_history(learner,10)
    if coach_rows:
        st.dataframe([{'drill':r['drill_id'],'focus':r['goal'],'difficulty':r['difficulty'],
                       'key_accuracy':f"{r['accuracy']:.0%}",'mistakes':r['mistakes']}
                      for r in coach_rows],hide_index=True,use_container_width=True)
    else:st.caption('No completed keyboard coaching missions yet.')
    st.subheader('Actual tool execution log')
    logs=db.tool_logs(learner,20)
    if logs:
        st.dataframe([{'time_utc':r['created_at'],'source':r['source'],'tool':r['name'],
                       'arguments':r['args'],'result':r['result'][:180]} for r in logs],hide_index=True)
    else:st.caption('No agent tools called yet. Complete the assessment and choose a learning activity.')
    st.caption('Logs labelled "gemini" come from model-chosen function calls. "rules" means the deterministic fallback controller.')


def show_schedule(learner):
    st.title('🗓️ Daily Goals, Reminders & Smart Scheduling')
    pref=db.preferences(learner)
    with st.form('goal-form'):
        goal=st.selectbox('Daily practice target (minutes)',[15,30,45,60],index=[15,30,45,60].index(pref['goal_minutes']))
        preferred=st.time_input('Preferred training / reminder time',value=datetime.strptime(pref['reminder_time'],'%H:%M').time())
        tz=st.selectbox('Timezone',['Asia/Kuala_Lumpur','Asia/Singapore','UTC','Europe/London','America/New_York'],
                        index=(['Asia/Kuala_Lumpur','Asia/Singapore','UTC','Europe/London','America/New_York'].index(pref['timezone']) if pref['timezone'] in ['Asia/Kuala_Lumpur','Asia/Singapore','UTC','Europe/London','America/New_York'] else 0))
        if st.form_submit_button('Save daily goal and in-app reminder'):
            db.save_preferences(learner,goal,preferred.strftime('%H:%M'),tz)
            st.success('Preferences saved. The reminder appears in-app after your chosen time.');st.rerun()
    st.divider()
    st.subheader('Google Calendar — optional local integration')
    st.caption('OAuth opens your Google browser consent screen. ToneTutor sees free/busy blocks, not event titles. It does not alter existing events.')
    if not scheduler.connected():
        st.info('Calendar is not connected. You can keep using in-app reminders without Google.')
        if st.button('Connect Google Calendar via OAuth'):
            try:scheduler.connect_local();st.success('Connected');st.rerun()
            except Exception as exc:st.error(f'Connection failed: {exc}')
        st.caption('You need Google Cloud OAuth credentials.json. See CALENDAR_SETUP.md.')
        return
    if st.button('Disconnect Google Calendar'):
        scheduler.disconnect();st.session_state.pop('suggestions',None);st.success('Local token deleted.');st.rerun()
    stored=db.calendar_sessions(learner)
    if stored:
        st.caption(f'{len(stored)} training event(s) created from this local prototype.')
        if st.button('Recheck my ToneTutor sessions for conflicts'):
            try:
                conflicts=scheduler.check_existing_training_conflicts(stored)
                if conflicts:
                    st.warning(f'{len(conflicts)} possible change(s) or conflict(s).')
                    for info in conflicts:st.write(info['begins']+' — '+info['message'])
                    st.info('Request a new free slot below if needed. Existing events are never modified automatically.')
                else:st.success('No conflicts detected in the checked event window.')
            except Exception as exc:st.error(str(exc))
    if st.button('Check availability and suggest times',type='primary'):
        try:
            from agent import calendar_recommendation
            # The model can call read-only calendar tools; creating an event remains a separate confirmed UI action.
            response=calendar_recommendation(learner,mode=st.session_state.tutor_mode)
            if response.get('error'):st.error(response['error'])
            else:
                st.session_state.suggestions=response['slots'];st.session_state.suggestions_for=learner
                st.session_state.suggested_index=response['index'];st.session_state.schedule_reason=response.get('reason','')
                st.session_state.suggested_mode=response['mode']
        except Exception as exc:st.error(str(exc))
    options=st.session_state.get('suggestions',[]) if st.session_state.get('suggestions_for')==learner else []
    if options:
        labels=[f"{s['start']} · {s['duration_minutes']} min" for s in options]
        st.caption(f"Suggested by {st.session_state.get('suggested_mode','rules')} controller: {st.session_state.get('schedule_reason','')}")
        ix=st.radio('Review a proposed free slot',list(range(len(options))),
                    index=min(st.session_state.get('suggested_index',0),len(options)-1),format_func=lambda i:labels[i])
        plan=db.get_plan(learner)
        topic=(plan['skill']+' practice') if plan else 'beginner ear training'
        st.write('Suggested topic: **'+topic+'**')
        st.warning('An event is created only when you click Confirm. Busy availability is rechecked before creation.')
        if st.button('Confirm and create my training event',type='primary'):
            try:
                event=scheduler.create_event(options[ix],topic,db.preferences(learner)['timezone'])
                if event.get('id'):db.record_calendar_session(learner,event['id'],options[ix],topic)
                st.success('Google Calendar event created.')
                if event.get('htmlLink'):st.link_button('Open calendar event',event['htmlLink'])
                st.session_state.pop('suggestions',None)
            except Exception as exc:st.error(f'Could not create event: {exc}')


with st.sidebar:
    st.title('ToneTutor AI')
    st.caption('DEMO · local prototype')
    typed=st.text_input('Anonymous learner ID',st.session_state.learner)
    if typed!=st.session_state.learner:
        try:
            db.ensure_learner(typed)
            tick_practice();st.session_state.practice_active=False
            st.session_state.learner=typed
            st.session_state.feedback=None;st.session_state.piano_steps=[]
            st.session_state.pop('agent_message',None)
            st.rerun()
        except ValueError as exc:st.error(str(exc))
    learner=st.session_state.learner
    db.ensure_learner(learner)
    st.session_state.tutor_mode=st.radio('Tutor controller', ['rules','gemini'],
        index=0 if st.session_state.get('tutor_mode','rules')=='rules' else 1,
        format_func=lambda v:'Offline rules' if v=='rules' else 'Gemini AI')
    if st.session_state.tutor_mode=='gemini' and not os.getenv('GEMINI_API_KEY'):
        st.warning('Gemini API key missing; the app will fall back to offline rules.')
    st.divider()
    for name,ico in [('Dashboard','🏠'),('Lessons','📚'),('Training','🎧'),('Piano','🎹'),('Notation','🎼'),('Schedule','🗓️'),('Progress','📊')]:
        if st.button(ico+' '+name,use_container_width=True,key='nav-'+name):set_page(name)
    st.divider()
    st.caption('Your anonymous data stays in the local SQLite file. The Google OAuth token is stored locally on this demo machine only.')

page=st.session_state.page
if page=='Dashboard':show_dashboard(learner)
elif page=='Lessons':show_lessons(learner)
elif page=='Training':show_training(learner,st.session_state.tutor_mode)
elif page=='Piano':show_piano(learner)
elif page=='Notation':show_notation(learner)
elif page=='Schedule':show_schedule(learner)
elif page=='Progress':show_progress(learner)

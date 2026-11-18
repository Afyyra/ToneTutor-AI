"""SQLite persistence for a single-machine local demonstration, keyed by anonymous learner ID."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from music import PITCH_CLASSES, ALL_KEYS
from exercises import SKILLS, LEVELS, public, grade

DB = Path(os.getenv('TONETUTOR_DB', str(Path(__file__).with_name('tonetutor_v2.db'))))
DEFAULT_TZ='Asia/Kuala_Lumpur'

@contextmanager
def connection():
    DB.parent.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(DB,timeout=10)
    conn.row_factory=sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute('PRAGMA busy_timeout = 5000')
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback(); raise
    finally: conn.close()

def initialize():
    with connection() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS learners (
            id TEXT PRIMARY KEY, assessment_complete INTEGER NOT NULL DEFAULT 0,
            goal_minutes INTEGER NOT NULL DEFAULT 15, reminder_time TEXT NOT NULL DEFAULT '19:00',
            timezone TEXT NOT NULL DEFAULT 'Asia/Kuala_Lumpur',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, learner_id TEXT NOT NULL REFERENCES learners(id),
            exercise_id TEXT NOT NULL, skill TEXT NOT NULL, difficulty TEXT NOT NULL,
            note_target TEXT, submitted TEXT NOT NULL, correct INTEGER NOT NULL,
            result TEXT NOT NULL, assessment INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS attempts_learner_idx ON attempts(learner_id,id);
        CREATE TABLE IF NOT EXISTS assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT, learner_id TEXT NOT NULL REFERENCES learners(id),
            exercise_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE UNIQUE INDEX IF NOT EXISTS only_one_active ON assignments(learner_id) WHERE status='active';
        CREATE TABLE IF NOT EXISTS plans (
            learner_id TEXT PRIMARY KEY REFERENCES learners(id), skill TEXT NOT NULL,
            difficulty TEXT NOT NULL, focus_note TEXT, contrast_note TEXT,
            reason TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS tool_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, learner_id TEXT NOT NULL REFERENCES learners(id),
            name TEXT NOT NULL, args TEXT NOT NULL, result TEXT NOT NULL,
            source TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS practice_time (
            id INTEGER PRIMARY KEY AUTOINCREMENT, learner_id TEXT NOT NULL REFERENCES learners(id),
            day TEXT NOT NULL, seconds INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS completed_lessons (
            learner_id TEXT NOT NULL REFERENCES learners(id), topic TEXT NOT NULL,
            completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(learner_id,topic)
        );
        CREATE TABLE IF NOT EXISTS calendar_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            learner_id TEXT NOT NULL REFERENCES learners(id),
            event_id TEXT NOT NULL UNIQUE,
            begins TEXT NOT NULL, ends TEXT NOT NULL, topic TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS support (
            id INTEGER PRIMARY KEY AUTOINCREMENT, learner_id TEXT NOT NULL REFERENCES learners(id),
            message TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS piano_coach_missions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            learner_id TEXT NOT NULL REFERENCES learners(id),
            drill_id TEXT NOT NULL,
            target_json TEXT NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            outcome_json TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS only_one_coach_mission
          ON piano_coach_missions(learner_id) WHERE status='active';
        CREATE TABLE IF NOT EXISTS piano_jam_phrases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            learner_id TEXT NOT NULL REFERENCES learners(id),
            played_json TEXT NOT NULL,
            features_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        ''')

def ensure_learner(learner_id):
    if not isinstance(learner_id,str) or not (1<=len(learner_id)<=48) or not all(x.isalnum() or x in '-_' for x in learner_id):
        raise ValueError('Learner ID must contain 1–48 letters/numbers, - or _')
    with connection() as c: c.execute('INSERT OR IGNORE INTO learners(id) VALUES (?)',(learner_id,))

def preferences(learner_id):
    with connection() as c:
        row=c.execute('SELECT goal_minutes,reminder_time,timezone FROM learners WHERE id=?',(learner_id,)).fetchone()
    if row is None: raise ValueError('Unknown learner')
    return dict(row)

def save_preferences(learner_id,goal_minutes,reminder_time,timezone=DEFAULT_TZ):
    if goal_minutes not in (15,30,45,60): raise ValueError('Invalid training duration')
    if not isinstance(reminder_time,str) or len(reminder_time)!=5: raise ValueError('Invalid time')
    h,m=reminder_time.split(':')
    if not (h.isdigit() and m.isdigit() and 0<=int(h)<24 and 0<=int(m)<60): raise ValueError('Invalid time')
    ZoneInfo(timezone)
    with connection() as c:
        c.execute('UPDATE learners SET goal_minutes=?,reminder_time=?,timezone=? WHERE id=?',
                  (goal_minutes,reminder_time,timezone,learner_id))

def mark_assessment_done(learner_id):
    with connection() as c:c.execute('UPDATE learners SET assessment_complete=1 WHERE id=?',(learner_id,))

def active(learner_id):
    with connection() as c:
        row=c.execute("SELECT id,exercise_json FROM assignments WHERE learner_id=? AND status='active' ORDER BY id DESC LIMIT 1",(learner_id,)).fetchone()
    return {**json.loads(row['exercise_json']), '_assignment_id': row['id']} if row else None

def assign(learner_id,ex):
    with connection() as c:
        row=c.execute("SELECT id,exercise_json FROM assignments WHERE learner_id=? AND status='active'",(learner_id,)).fetchone()
        if row: return {'assigned':False,'exercise':public(json.loads(row['exercise_json'])),'message':'Already assigned'}
        c.execute('INSERT INTO assignments(learner_id,exercise_json) VALUES (?,?)',(learner_id,json.dumps(ex)))
    return {'assigned':True,'exercise':public(ex)}

def submit(learner_id,submitted,assessment=False):
    with connection() as c:
        row=c.execute("SELECT id,exercise_json FROM assignments WHERE learner_id=? AND status='active'",(learner_id,)).fetchone()
        if row is None: raise ValueError('No active exercise')
        ex=json.loads(row['exercise_json'])
        result=grade(ex,submitted)
        # A single transaction keeps answer submission and assignment status consistent.
        c.execute("UPDATE assignments SET status='completed' WHERE id=?",(row['id'],))
        target=ex['notes'][0] if ex['type'] in ('identify_note','contrast_notes') else None
        c.execute('''INSERT INTO attempts(learner_id,exercise_id,skill,difficulty,note_target,submitted,correct,result,assessment)
                     VALUES (?,?,?,?,?,?,?,?,?)''',
                  (learner_id,ex['id'],ex['skill'],ex['difficulty'],target,json.dumps(submitted),int(result['correct']),
                   json.dumps(result),int(assessment)))
    return result

def recent_attempts(learner_id,limit=40):
    with connection() as c:
        rows=c.execute('SELECT * FROM attempts WHERE learner_id=? ORDER BY id DESC LIMIT ?', (learner_id,limit)).fetchall()
    return [dict(row,submitted=json.loads(row['submitted']),result=json.loads(row['result'])) for row in rows]

def set_plan(learner_id,skill,difficulty,reason,focus_note=None,contrast_note=None):
    with connection() as c:
        c.execute('''INSERT INTO plans(learner_id,skill,difficulty,focus_note,contrast_note,reason) VALUES(?,?,?,?,?,?)
          ON CONFLICT(learner_id) DO UPDATE SET skill=excluded.skill,difficulty=excluded.difficulty,
          focus_note=excluded.focus_note,contrast_note=excluded.contrast_note,reason=excluded.reason,
          updated_at=CURRENT_TIMESTAMP''',(learner_id,skill,difficulty,focus_note,contrast_note,reason))

def get_plan(learner_id):
    with connection() as c:
        r=c.execute('SELECT skill,difficulty,focus_note,contrast_note,reason,updated_at FROM plans WHERE learner_id=?',(learner_id,)).fetchone()
    return dict(r) if r else None

def note_statistics(learner_id):
    """Identify note confusion by specific correct note and learner's selected wrong note."""
    stats={pc:{'attempts':0,'correct':0,'confused_with':{}} for pc in PITCH_CLASSES}
    for row in recent_attempts(learner_id,500):
        if row['skill']!='notes' or not row['note_target']: continue
        target=row['note_target'][:-1]
        if target not in stats: continue
        s=stats[target];s['attempts']+=1;s['correct']+=int(row['correct'])
        if not row['correct'] and isinstance(row['submitted'],str):
            mis=row['submitted'][:-1]
            if mis in PITCH_CLASSES:
                s['confused_with'][mis]=s['confused_with'].get(mis,0)+1
    return stats

def get_profile(learner_id):
    with connection() as c:
        user=c.execute('SELECT * FROM learners WHERE id=?',(learner_id,)).fetchone()
        if user is None: raise ValueError('Unknown learner')
        rows=c.execute('SELECT skill,COUNT(*) attempts,SUM(correct) correct FROM attempts WHERE learner_id=? GROUP BY skill',(learner_id,)).fetchall()
    stats={s:{'attempts':0,'correct':0,'accuracy':None} for s in SKILLS}
    for row in rows:
        if row['skill'] in stats:
            attempts=row['attempts'];correct=row['correct']
            stats[row['skill']]={'attempts':attempts,'correct':correct,'accuracy':round(100*correct/attempts)}
    return {'learner_id':learner_id,'assessment_complete':bool(user['assessment_complete']),
            'skills':stats,'notes':note_statistics(learner_id),
            'plan':get_plan(learner_id),'preferences':preferences(learner_id)}

def add_seconds(learner_id,seconds,when=None):
    if not isinstance(seconds,int) or seconds<0 or seconds>7200: raise ValueError('Invalid duration')
    if seconds==0:return
    prefs=preferences(learner_id);day=(when or datetime.now(ZoneInfo(prefs['timezone']))).date().isoformat()
    with connection() as c:c.execute('INSERT INTO practice_time(learner_id,day,seconds) VALUES (?,?,?)',(learner_id,day,seconds))

def daily_times(learner_id,days=14):
    prefs=preferences(learner_id)
    today=datetime.now(ZoneInfo(prefs['timezone'])).date()
    cutoff=(today-timedelta(days=days-1)).isoformat()
    with connection() as c:
        rows=c.execute('SELECT day,SUM(seconds) seconds FROM practice_time WHERE learner_id=? AND day>=? GROUP BY day',(learner_id,cutoff)).fetchall()
    observed={r['day']:r['seconds'] for r in rows}
    return [{'day':(today-timedelta(days=i)).isoformat(),'minutes':round(observed.get((today-timedelta(days=i)).isoformat(),0)/60,1)} for i in reversed(range(days))]

def complete_lesson(learner_id,topic):
    with connection() as c: c.execute('INSERT OR IGNORE INTO completed_lessons(learner_id,topic) VALUES (?,?)',(learner_id,topic))

def completed_lessons(learner_id):
    with connection() as c: rows=c.execute('SELECT topic FROM completed_lessons WHERE learner_id=?',(learner_id,)).fetchall()
    return {r['topic'] for r in rows}

def add_support(learner_id,message):
    with connection() as c:c.execute('INSERT INTO support(learner_id,message) VALUES(?,?)',(learner_id,message[:900]))

def latest_support(learner_id):
    with connection() as c:r=c.execute('SELECT message FROM support WHERE learner_id=? ORDER BY id DESC LIMIT 1',(learner_id,)).fetchone()
    return r['message'] if r else ''

def log_tool(learner_id,name,args,result,source):
    with connection() as c:c.execute('INSERT INTO tool_logs(learner_id,name,args,result,source) VALUES(?,?,?,?,?)',
                                    (learner_id,name,json.dumps(args,default=str),json.dumps(result,default=str),source))

def tool_logs(learner_id,limit=20):
    with connection() as c: rows=c.execute('SELECT name,args,result,source,created_at FROM tool_logs WHERE learner_id=? ORDER BY id DESC LIMIT ?',(learner_id,limit)).fetchall()
    return [dict(r) for r in rows]


def record_calendar_session(learner_id,event_id,slot,topic):
    if not isinstance(event_id,str) or not event_id:raise ValueError('Invalid event ID')
    with connection() as c:
        c.execute('INSERT OR IGNORE INTO calendar_sessions(learner_id,event_id,begins,ends,topic) VALUES(?,?,?,?,?)',
                  (learner_id,event_id,slot['start'],slot['end'],topic[:70]))

def calendar_sessions(learner_id):
    with connection() as c:
        rows=c.execute('SELECT event_id,begins,ends,topic FROM calendar_sessions WHERE learner_id=? ORDER BY id DESC LIMIT 30',(learner_id,)).fetchall()
    return [dict(row) for row in rows]


def coach_active(learner_id):
    """Piano coaching has its own activity record, distinct from quiz assignments."""
    with connection() as c:
        row=c.execute("SELECT * FROM piano_coach_missions WHERE learner_id=? AND status='active'",
                      (learner_id,)).fetchone()
    return ({'id':row['id'],'drill_id':row['drill_id'],
             'notes':json.loads(row['target_json']),'reason':row['reason']} if row else None)


def start_coach_mission(learner_id,drill_id,notes,reason):
    if not isinstance(drill_id,str) or not drill_id or len(drill_id)>60:
        raise ValueError('Invalid piano drill ID')
    if not isinstance(notes,list) or not (1<=len(notes)<=12) or any(note not in ALL_KEYS for note in notes):
        raise ValueError('Piano targets must be C4–B5 notes')
    if not isinstance(reason,str) or not reason.strip() or len(reason)>240:
        raise ValueError('Invalid piano coaching reason')
    with connection() as c:
        row=c.execute("SELECT * FROM piano_coach_missions WHERE learner_id=? AND status='active'",
                      (learner_id,)).fetchone()
        if row:
            return {'id':row['id'],'drill_id':row['drill_id'],
                    'notes':json.loads(row['target_json']),'reason':row['reason']}
        cursor=c.execute('INSERT INTO piano_coach_missions(learner_id,drill_id,target_json,reason) VALUES (?,?,?,?)',
                         (learner_id,drill_id,json.dumps(notes),reason))
        return {'id':cursor.lastrowid,'drill_id':drill_id,'notes':list(notes),'reason':reason}


COACH_INPUT_SOURCES=('on_screen','browser_webcam')


def complete_coach_mission(learner_id,mission_id,presses,input_source='on_screen'):
    """Save a full keyboard trace and objective note accuracy in one transaction."""
    if not isinstance(mission_id,int) or mission_id<=0:
        raise ValueError('Invalid mission ID')
    if input_source not in COACH_INPUT_SOURCES:
        raise ValueError('Invalid input source')
    if not isinstance(presses,list) or not 1<=len(presses)<=80 or any(n not in ALL_KEYS for n in presses):
        raise ValueError('Invalid piano note trace')
    with connection() as c:
        row=c.execute('SELECT * FROM piano_coach_missions WHERE id=? AND learner_id=?',
                      (mission_id,learner_id)).fetchone()
        if row is None:raise ValueError('Unknown piano mission')
        if row['status']=='completed':return json.loads(row['outcome_json'])
        if row['status']!='active':raise ValueError('Mission is not active')
        targets=json.loads(row['target_json'])
        progress=0;events=[]
        for played in presses:
            if progress>=len(targets):raise ValueError('Extra notes after mission completion')
            expected=targets[progress];correct=(played==expected)
            events.append({'played':played,'expected':expected,'correct':correct})
            if correct:progress+=1
        if progress!=len(targets):raise ValueError('Finish all required notes before saving a result')
        outcome={'drill_id':row['drill_id'],'notes_completed':progress,'attempted_notes':len(presses),
                 'mistakes':len(presses)-progress,'accuracy':round(progress/len(presses),3),
                 'events':events,'input_source':input_source}
        c.execute("UPDATE piano_coach_missions SET status='completed',outcome_json=?,completed_at=CURRENT_TIMESTAMP WHERE id=? AND status='active'",
                  (json.dumps(outcome),mission_id))
    return outcome


def cancel_coach_mission(learner_id):
    """Learner-controlled exit without fabricating a scored attempt."""
    with connection() as c:
        c.execute("UPDATE piano_coach_missions SET status='cancelled' WHERE learner_id=? AND status='active'",(learner_id,))


def coach_history(learner_id,limit=10):
    if type(limit) is not int or not 1<=limit<=40:raise ValueError('Invalid history limit')
    with connection() as c:
        rows=c.execute("SELECT id,drill_id,outcome_json,created_at FROM piano_coach_missions WHERE learner_id=? AND status='completed' ORDER BY id DESC LIMIT ?",
                       (learner_id,limit)).fetchall()
    from piano_coach import DRILLS  # lazy import avoids database module circular import
    output=[]
    for row in rows:
        outcome=json.loads(row['outcome_json'])
        detail=DRILLS.get(row['drill_id'],{})
        output.append({'id':row['id'],'drill_id':row['drill_id'],'input_source':outcome.get('input_source','on_screen'),
                       'goal':detail.get('goal','Unknown'),
                       'difficulty':detail.get('level','unknown'),
                       'accuracy':outcome['accuracy'],'mistakes':outcome['mistakes'],
                       'date':row['created_at']})
    return output


def save_jam_phrase(learner_id,notes,features):
    if not isinstance(notes,list) or not (3<=len(notes)<=20) or any(n not in ALL_KEYS for n in notes):
        raise ValueError('Record 3–20 valid virtual piano notes')
    if not isinstance(features,dict) or len(json.dumps(features))>1500:
        raise ValueError('Invalid phrase analysis')
    with connection() as c:
        cursor=c.execute('INSERT INTO piano_jam_phrases(learner_id,played_json,features_json) VALUES(?,?,?)',
                         (learner_id,json.dumps(notes),json.dumps(features)))
    return cursor.lastrowid


def jam_history(learner_id,limit=6):
    if type(limit) is not int or not 1<=limit<=20:raise ValueError('Invalid jam history limit')
    with connection() as c:
        rows=c.execute('SELECT id,played_json,features_json,created_at FROM piano_jam_phrases WHERE learner_id=? ORDER BY id DESC LIMIT ?',
                       (learner_id,limit)).fetchall()
    return [{'id':r['id'],'notes':json.loads(r['played_json']),
             'features':json.loads(r['features_json']),'date':r['created_at']} for r in rows]

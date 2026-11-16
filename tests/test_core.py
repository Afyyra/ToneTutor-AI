import os
import json
import math
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

import audio
import database as db
from music import frequency,midi,note_from_midi,normalise,semitones,scale,chord,PITCH_CLASSES
from exercises import generate,grade,SKILLS
from tools import LearnerTools
from agent import offline_decision
import scheduler
from notation import staff_svg

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        db.DB=Path(self.temp.name)/'test.db'
        db.initialize();db.ensure_learner('USER_1')

    def tearDown(self):self.temp.cleanup()

    def test_all_12_chromatic_notes_and_enharmonics(self):
        self.assertEqual(len(PITCH_CLASSES),12)
        self.assertEqual(normalise('Db4'),'C#4')
        self.assertEqual(normalise('Bb4'),'A#4')
        self.assertAlmostEqual(frequency('A4'),440,places=4)
        self.assertAlmostEqual(frequency('C5')/frequency('C4'),2,places=3)
        self.assertEqual(semitones('C4','D4'),2)
        self.assertEqual(semitones('E4','F4'),1)

    def test_scale_and_chords(self):
        self.assertEqual(scale('C4'),['C4','D4','E4','F4','G4','A4','B4','C5'])
        self.assertEqual(chord('C4'),['C4','E4','G4'])
        self.assertEqual(chord('C4','minor'),['C4','D#4','G4'])

    def test_wav_header(self):
        b=audio.wav_bytes(['C4','E4','G4'])
        self.assertTrue(b.startswith(b'RIFF'))
        self.assertGreater(len(b),4000)

    def test_generate_every_skill(self):
        for skill in SKILLS:
            ex=generate(skill,'easy')
            self.assertTrue(ex['id']);self.assertEqual(ex['skill'],skill)
            self.assertIn('correct_answer',ex)

    def test_unique_random_exercise_ids(self):
        a,b=generate('pitch'),generate('pitch')
        self.assertNotEqual(a['id'],b['id'])

    def test_note_contrast_and_confusion(self):
        for i in range(3):
            e=generate('notes','easy',focus_note='C4',contrast_note='D4',preferred_type='contrast_notes')
            # Force target C4 so we can test repeated specific mistakes.
            e['notes']=['C4'];e['correct_answer']='C4';e['options']=['C4','D4']
            db.assign('USER_1',e);res=db.submit('USER_1','D4')
            self.assertFalse(res['correct'])
        stats=db.note_statistics('USER_1')
        self.assertEqual(stats['C']['confused_with']['D'],3)
        db.mark_assessment_done('USER_1')
        outcome=offline_decision('USER_1')
        self.assertEqual(db.get_plan('USER_1')['skill'],'notes')
        self.assertEqual(db.get_plan('USER_1')['focus_note'],'C4')
        self.assertEqual(db.get_plan('USER_1')['contrast_note'],'D4')
        self.assertEqual(outcome['mode'],'rules')
        self.assertIsNotNone(db.active('USER_1'))

    def test_sequence_grading_partial_credit(self):
        ex=generate('piano','easy',preferred_type='piano_follow')
        desired=ex['correct_answer']
        self.assertTrue(grade(ex,desired)['correct'])
        result=grade(ex,desired[:2])
        self.assertFalse(result['correct'])
        self.assertEqual(result['total'],len(desired))

    def test_assign_only_one_active_and_transaction(self):
        a=generate('notes','easy');b=generate('notes','easy')
        self.assertTrue(db.assign('USER_1',a)['assigned'])
        self.assertFalse(db.assign('USER_1',b)['assigned'])
        with self.assertRaises(ValueError):db.submit('USER_1','WRONG_OPTION')
        self.assertIsNotNone(db.active('USER_1'))
        submitted=a['correct_answer'];self.assertTrue(db.submit('USER_1',submitted)['correct'])
        self.assertIsNone(db.active('USER_1'))

    def test_tool_validation_and_logs(self):
        t=LearnerTools('USER_1',source='test')
        self.assertIn('error',t.execute('update_learning_plan',{'skill':'invalid','difficulty':'easy','reason':'x'}))
        self.assertTrue(t.execute('update_learning_plan',{'skill':'notes','difficulty':'easy','reason':'Practise C4'})['updated'])
        self.assertTrue(len(db.tool_logs('USER_1'))>=2)
        self.assertEqual(t.execute('assign_exercise',{'skill':'notes','difficulty':'easy'}).get('error'),
                         'Finish the initial assessment first')

    def test_daily_goal(self):
        db.save_preferences('USER_1',30,'21:30')
        db.add_seconds('USER_1',900)
        self.assertEqual(db.preferences('USER_1')['goal_minutes'],30)
        self.assertEqual(db.daily_times('USER_1',1)[0]['minutes'],15)

    def test_schedule_avoids_busy(self):
        tz=ZoneInfo('Asia/Kuala_Lumpur')
        now=datetime(2026,11,7,8,0,tzinfo=tz)
        busy=[(datetime(2026,11,7,19,0,tzinfo=tz),datetime(2026,11,7,20,0,tzinfo=tz))]
        slots=scheduler.candidate_slots(now,30,'19:00',busy,days=1)
        self.assertTrue(slots)
        for slot in slots:
            self.assertFalse(scheduler.overlaps(datetime.fromisoformat(slot['start']),datetime.fromisoformat(slot['end']),busy))

    def test_calendar_creation_requires_confirmation_and_recheck(self):
        class Fake:
            def __init__(self):self.created=0
            def freebusy(self):return self
            def query(self,body):return self
            def execute(self):
                if self.created: return {'id':'created'}
                return {'calendars':{'primary':{'busy':[]}}}
            def events(self):return self
            def insert(self,calendarId,body):
                assert calendarId=='primary'
                assert body['reminders']['overrides'][0]['minutes']==10
                self.created+=1
                return self
        tz=ZoneInfo('Asia/Kuala_Lumpur');now=datetime(2026,11,7,8,0,tzinfo=tz)
        slot={'start':(now+timedelta(hours=2)).isoformat(),'end':(now+timedelta(hours=2,minutes=15)).isoformat()}
        fake=Fake()
        self.assertEqual(scheduler.create_event(slot,'pitch practice','Asia/Kuala_Lumpur',api=fake,now=now)['id'],'created')
        self.assertEqual(fake.created,1)

    def test_recovered_note_not_forced_indefinitely(self):
        # First establish C4→D4 confusion, then three correct C4 matches.
        for submitted in ['D4','D4','D4','C4','C4','C4']:
            ex=generate('notes','easy',preferred_type='contrast_notes')
            ex['notes']=['C4'];ex['correct_answer']='C4';ex['options']=['C4','D4']
            db.assign('USER_1',ex);db.submit('USER_1',submitted)
        db.mark_assessment_done('USER_1')
        offline_decision('USER_1')
        # Recovered note may be chosen for other reasons, but the C/D pair is not mandatory.
        self.assertIsNone(db.get_plan('USER_1')['contrast_note'])

    def test_calendar_conflict_detects_another_event_by_times_only(self):
        tz=ZoneInfo('Asia/Kuala_Lumpur')
        a=datetime(2026,11,7,10,0,tzinfo=tz)
        b=a+timedelta(minutes=30)
        rows=[{'event_id':'our-training','begins':a.isoformat(),'ends':b.isoformat(),'topic':'pitch'}]
        class Fake:
            def events(self):return self
            def list(self,**kwargs):return self
            def execute(self):
                return {'items':[{'id':'our-training','start':{'dateTime':a.isoformat()},'end':{'dateTime':b.isoformat()}},
                                 {'id':'meeting','start':{'dateTime':(a+timedelta(minutes=10)).isoformat()},
                                  'end':{'dateTime':(b+timedelta(minutes=10)).isoformat()}}]}
        conflicts=scheduler.check_existing_training_conflicts(rows,api=Fake())
        self.assertTrue(any('conflicts' in c['message'] for c in conflicts))

    def test_notation_svg(self):
        svg=staff_svg('C4','treble')
        self.assertIn('<svg',svg)
        self.assertIn('ellipse',svg)
        self.assertIn('line',svg)

if __name__=='__main__':unittest.main()

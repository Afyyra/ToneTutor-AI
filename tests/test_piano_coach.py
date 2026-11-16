"""Offline and mocked-agent verification of the piano coaching additions.

These tests do not replace an interactive browser or live Gemini API test.
"""
import os
import sys
import types
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import database as db
import piano_coach as coach


class PianoCoachTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        db.DB=Path(self.temp.name)/'piano_test.sqlite'
        db.initialize()
        db.ensure_learner('LEARNER_ONE')
        db.ensure_learner('LEARNER_TWO')

    def tearDown(self):
        self.temp.cleanup()

    def test_rule_coach_writes_a_real_mission_and_tracks_mistakes(self):
        selected=coach.next_piano_mission('LEARNER_ONE',mode='rules',goal='Key location')
        self.assertEqual(selected['mode'],'rules')
        target=selected['mission']['notes']
        bad='G#4' if target[0]!='G#4' else 'A4'
        outcome=db.complete_coach_mission('LEARNER_ONE',selected['mission']['id'],[bad]+target)
        self.assertEqual(outcome['mistakes'],1)
        self.assertEqual(outcome['notes_completed'],len(target))
        self.assertLess(outcome['accuracy'],1)
        self.assertEqual(db.complete_coach_mission('LEARNER_ONE',selected['mission']['id'],[bad]+target),outcome)
        self.assertIsNone(db.coach_active('LEARNER_ONE'))
        self.assertEqual(db.coach_history('LEARNER_ONE')[0]['accuracy'],outcome['accuracy'])
        self.assertTrue(all(r['source']=='rules' for r in db.tool_logs('LEARNER_ONE')))

    def test_piano_per_key_feedback_does_not_advance_on_wrong_taps(self):
        notes=['C4','D4','E4']
        first=coach.process_piano_press(notes,'F#4',[])
        self.assertEqual(first['progress'],0)
        self.assertFalse(first['history'][0]['correct'])
        second=coach.process_piano_press(notes,'C4',first['history'])
        self.assertEqual(second['progress'],1)
        third=coach.process_piano_press(notes,'D4',second['history'])
        fourth=coach.process_piano_press(notes,'E4',third['history'])
        self.assertTrue(fourth['finished'])
        self.assertEqual(fourth['progress'],3)

    def test_coach_adapts_from_two_strong_missions_and_limits_goals(self):
        for _ in range(2):
            choice=coach.next_piano_mission('LEARNER_ONE',goal='Key location')
            self.assertEqual(choice['mission']['difficulty'],'easy')
            db.complete_coach_mission('LEARNER_ONE',choice['mission']['id'],choice['mission']['notes'])
        next_one=coach.next_piano_mission('LEARNER_ONE',goal='Key location')
        self.assertEqual(next_one['mission']['difficulty'],'medium')
        self.assertEqual(next_one['mission']['goal'],'Key location')

    def test_learner_scope_and_invalid_drill_rejection(self):
        t=coach.PianoCoachTools('LEARNER_ONE',source='gemini',goal='Black keys')
        bad=t.execute('set_piano_coach_mission',{'drill_id':'triad_start','reason':'Wrong goal'})
        self.assertIn('error',bad)
        bad2=t.execute('set_piano_coach_mission',{'drill_id':'nothing_real','reason':'Fake'})
        self.assertIn('error',bad2)
        self.assertIsNone(db.coach_active('LEARNER_ONE'))
        chosen=t.execute('set_piano_coach_mission',{'drill_id':'black_neighbor','reason':'Work with C-sharp'})
        self.assertEqual(chosen['mission']['drill_id'],'black_neighbor')
        self.assertIsNone(db.coach_active('LEARNER_TWO'))
        self.assertEqual(db.coach_history('LEARNER_TWO'),[])
        with self.assertRaises(ValueError):
            db.complete_coach_mission('LEARNER_TWO',chosen['mission']['id'],chosen['mission']['notes'])

    def test_creative_jam_is_not_a_quiz(self):
        phrase=['C4','E4','G4','G4','C5']
        data=coach.describe_jam(phrase)
        self.assertEqual(data['notes_played'],5)
        self.assertEqual(data['repeated_notes'],1)
        out=coach.respond_to_jam('LEARNER_ONE',phrase,mode='rules')
        self.assertIn(out['direction_id'],coach.JAM_DIRECTIONS)
        self.assertIn('prompt',out)
        self.assertNotIn('correct',out)
        self.assertEqual(db.jam_history('LEARNER_ONE')[0]['notes'],phrase)
        self.assertEqual(db.jam_history('LEARNER_TWO'),[])

    def test_jam_tool_rejects_invented_direction(self):
        t=coach.JamCoachTools('LEARNER_ONE')
        bad=t.execute('set_piano_jam_direction',{'direction_id':'unlock_user_data','reason':'No'})
        self.assertIn('error',bad)
        self.assertIsNone(t.chosen)

    def test_missing_gemini_falls_back_without_pretending_to_be_ai(self):
        with patch.dict(os.environ,{'GEMINI_API_KEY':''}):
            r=coach.next_piano_mission('LEARNER_ONE','gemini','Key location')
        self.assertEqual(r['mode'],'rules')
        self.assertIn('warning',r)
        self.assertTrue(all(e['source']=='rules' for e in db.tool_logs('LEARNER_ONE')))

    def test_mock_gemini_creative_jam_calls_tools(self):
        db.save_jam_phrase('LEARNER_ONE',['C4','E4','G4'],
                           coach.describe_jam(['C4','E4','G4']))
        class Part:
            @staticmethod
            def from_text(text):return ('text',text)
            @staticmethod
            def from_function_response(name,response):return ('response',name,response)
        class Content:
            def __init__(self,role,parts):self.role=role;self.parts=parts
        fake_types=types.SimpleNamespace(
            Part=Part,Content=Content,
            FunctionDeclaration=lambda **kwargs:types.SimpleNamespace(**kwargs),
            Tool=lambda **kwargs:kwargs,
            GenerateContentConfig=lambda **kwargs:kwargs,
            AutomaticFunctionCallingConfig=lambda **kwargs:kwargs)
        class Client:
            def __init__(self,api_key):self.i=0
            @property
            def models(self):return self
            def generate_content(self,model,contents,config):
                self.i+=1
                fc=([types.SimpleNamespace(name='get_piano_jam_context',args={})]
                    if self.i==1 else
                    [types.SimpleNamespace(name='set_piano_jam_direction',
                      args={'direction_id':'motif_variation','reason':'Try varying the last note'})])
                return types.SimpleNamespace(function_calls=fc,candidates=[types.SimpleNamespace(
                    content=Content('model',fc))])
        g=types.ModuleType('google');genai=types.ModuleType('google.genai')
        genai.Client=Client;genai.types=fake_types;g.genai=genai
        with patch.dict(sys.modules,{'google':g,'google.genai':genai}),\
             patch.dict(os.environ,{'GEMINI_API_KEY':'MOCK_KEY','GEMINI_MODEL':'MOCK'}):
            r=coach.gemini_jam('LEARNER_ONE')
        self.assertEqual(r['mode'],'gemini')
        self.assertEqual(r['direction_id'],'motif_variation')
        self.assertTrue(all(log['source']=='gemini' for log in db.tool_logs('LEARNER_ONE')))

    def test_mock_gemini_calls_bounded_piano_tools(self):
        # Mock the SDK so this is a test of actual tool-response orchestration,
        # not a test of model quality or live provider authentication.
        class Part:
            @staticmethod
            def from_text(text):return ('text',text)
            @staticmethod
            def from_function_response(name,response):return ('response',name,response)
        class Content:
            def __init__(self,role,parts):self.role=role;self.parts=parts
        fake_types=types.SimpleNamespace(
            Part=Part,Content=Content,
            FunctionDeclaration=lambda **kwargs:types.SimpleNamespace(**kwargs),
            Tool=lambda **kwargs:kwargs,
            GenerateContentConfig=lambda **kwargs:kwargs,
            AutomaticFunctionCallingConfig=lambda **kwargs:kwargs,
        )
        class FakeClient:
            def __init__(self,api_key):self.round=0
            @property
            def models(self):return self
            def generate_content(self,model,contents,config):
                self.round+=1
                if self.round>1:self_test.assertEqual(contents[-1].role,'user')
                if self.round==1:actions=[('get_piano_coach_context',{})]
                else:actions=[('set_piano_coach_mission',
                               {'drill_id':'rising_three','reason':'Build stepwise confidence'})]
                fc=[types.SimpleNamespace(name=n,args=a) for n,a in actions]
                return types.SimpleNamespace(function_calls=fc,
                    candidates=[types.SimpleNamespace(content=Content('model',fc))])
        self_test=self
        g=types.ModuleType('google')
        genai=types.ModuleType('google.genai');genai.Client=FakeClient;genai.types=fake_types;g.genai=genai
        with patch.dict(sys.modules,{'google':g,'google.genai':genai}),\
             patch.dict(os.environ,{'GEMINI_API_KEY':'TEST','GEMINI_MODEL':'MOCK'}):
            result=coach.gemini_mission('LEARNER_ONE',goal='Melodic movement')
        self.assertEqual(result['mode'],'gemini')
        self.assertEqual(result['mission']['drill_id'],'rising_three')
        self.assertEqual(result['tool_calls'],2)
        self.assertEqual([r['source'] for r in db.tool_logs('LEARNER_ONE')],['gemini','gemini'])


if __name__=='__main__': unittest.main()

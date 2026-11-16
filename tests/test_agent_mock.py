"""Offline mock of the Gemini SDK to verify end-to-end tool-response orchestration.
Not a live API test: no Gemini API key/network is required.
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
import agent
import database as db


class MockGeminiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        db.DB=Path(self.temp.name)/'test.db'
        db.initialize()
        db.ensure_learner('AGENT_TEST')
        db.mark_assessment_done('AGENT_TEST')

    def tearDown(self):
        self.temp.cleanup()

    def test_gemini_can_call_tools_and_assign_real_exercise(self):
        class FakePart:
            @staticmethod
            def from_text(text):
                return ('text',text)

            @staticmethod
            def from_function_response(name,response):
                # This test would fail if agent.py passes the unsupported id keyword.
                return ('tool_result',name,response)

        class FakeContent:
            def __init__(self,role,parts):
                self.role=role
                self.parts=parts

        fake_types=types.SimpleNamespace(
            Part=FakePart,
            Content=FakeContent,
            FunctionDeclaration=lambda **kwargs: kwargs,
            Tool=lambda **kwargs: kwargs,
            GenerateContentConfig=lambda **kwargs: kwargs,
            AutomaticFunctionCallingConfig=lambda **kwargs: kwargs
        )

        class FakeClient:
            def __init__(self,api_key):
                self.calls=0
            def generate_content(self,model,contents,config):
                self.calls+=1
                if self.calls>1:
                    self_test.assertEqual(contents[-1].role,'user')
                actions=[
                  [('get_learning_profile',{}),('get_recent_attempts',{'limit':3})],
                  [('update_learning_plan',{'skill':'pitch','difficulty':'easy','reason':'Pitch needs practice'})],
                  [('assign_exercise',{'skill':'pitch','difficulty':'easy'})],
                ][self.calls-1]
                calls=[types.SimpleNamespace(name=n,args=a) for n,a in actions]
                return types.SimpleNamespace(
                    function_calls=calls,
                    candidates=[types.SimpleNamespace(content=FakeContent('model',calls))]
                )
            @property
            def models(self):return self

        self_test=self
        google=types.ModuleType('google')
        google_genai=types.ModuleType('google.genai')
        google_genai.Client=FakeClient
        google_genai.types=fake_types
        google.genai=google_genai

        with patch.dict(sys.modules,{'google':google,'google.genai':google_genai}), \
             patch.dict(os.environ,{'GEMINI_API_KEY':'TEST_KEY','GEMINI_MODEL':'FAKE_MODEL'}):
            result=agent.gemini_decision('AGENT_TEST')

        self.assertEqual(result['mode'],'gemini')
        self.assertEqual(result['tool_calls'],4)
        self.assertIsNotNone(db.active('AGENT_TEST'))
        self.assertEqual(db.get_plan('AGENT_TEST')['skill'],'pitch')
        self.assertEqual(len([r for r in db.tool_logs('AGENT_TEST') if r['source']=='gemini']),4)


if __name__=='__main__':unittest.main()

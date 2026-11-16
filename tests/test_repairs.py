"""Regression checks for earlier reported crashes and certificate-path failures."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime_tls import validate_ca_bundle
import certifi


class RepairTests(unittest.TestCase):
    def test_svg_source_is_passed_as_string_not_encoded_bytes(self):
        code = (Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8')
        self.assertNotIn(".encode('utf8')", code)
        self.assertIn("st.image(staff_svg(note,clef,show_name=True))", code)
        self.assertIn('st.image(rhythm_svg())', code)

    def test_function_response_does_not_pass_unsupported_id(self):
        code = (Path(__file__).resolve().parents[1] / 'agent.py').read_text(encoding='utf-8')
        self.assertNotIn("id=getattr(call,'id'", code)
        self.assertNotIn("id=getattr(fc,'id'", code)
        self.assertIn("types.Content(role='user',parts=results)", code)
        self.assertNotIn("role='tool'", code)
        coach = (Path(__file__).resolve().parents[1] / 'piano_coach.py').read_text(encoding='utf-8')
        self.assertNotIn("role='tool'", coach)
        self.assertEqual(coach.count("types.Content(role='user',parts=results)"), 1)
        self.assertEqual(coach.count("types.Content(role='user',parts=parts)"), 1)

    def test_missing_custom_ca_bundle_is_replaced_with_valid_certifi(self):
        bad = 'C:/ToneTutor_AI_complete_starter.venv/Lib/site-packages/certifi/cacert.pem'
        with patch.dict(os.environ, {'REQUESTS_CA_BUNDLE': bad, 'CURL_CA_BUNDLE': bad, 'SSL_CERT_FILE': bad}):
            modified = validate_ca_bundle()
            self.assertEqual(set(modified), {'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE', 'SSL_CERT_FILE'})
            self.assertEqual(os.environ['REQUESTS_CA_BUNDLE'], str(Path(certifi.where()).resolve()))

    def test_valid_custom_ca_bundle_is_preserved(self):
        good = str(Path(certifi.where()).resolve())
        with patch.dict(os.environ, {'REQUESTS_CA_BUNDLE': good}):
            validate_ca_bundle()
            self.assertEqual(os.environ['REQUESTS_CA_BUNDLE'], good)


if __name__ == '__main__':
    unittest.main()

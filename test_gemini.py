"""Check the current Gemini API key and model, without printing private values.
Run: python test_gemini.py
"""
import os
from pathlib import Path
from dotenv import load_dotenv
from runtime_tls import validate_ca_bundle

load_dotenv(dotenv_path=Path(__file__).with_name('.env'))


def main():
    key = os.getenv('GEMINI_API_KEY', '').strip()
    if not key:
        raise SystemExit('No GEMINI_API_KEY in .env. Offline rules mode needs no API key.')
    validate_ca_bundle()
    from google import genai
    model = os.getenv('GEMINI_MODEL', 'gemini-3.5-flash-lite')
    client = genai.Client(api_key=key)
    try:
        response = client.models.generate_content(
            model=model,
            contents='Reply exactly: ToneTutor Gemini connection OK.'
        )
        print('Model:', model)
        print('Response:', response.text)
    finally:
        client.close()


if __name__ == '__main__':
    main()

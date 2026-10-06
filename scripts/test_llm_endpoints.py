import os
import sys
import httpx
from dotenv import load_dotenv

load_dotenv()

gemini_key = os.getenv("GEMINI_API_KEY")
openai_key = os.getenv("OPENAI_API_KEY")
anthropic_key = os.getenv("ANTHROPIC_API_KEY")

verify_ssl = False if sys.platform == "win32" else True
client = httpx.Client(verify=verify_ssl, timeout=15.0)

print("--- Testing Gemini Models ---")
models_to_test = [
    "gemini-3.6-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-2.5-flash",
    "gemini-2.0-flash-exp",
    "gemini-1.5-pro",
    "gemini-2.0-flash-lite",
]

for m in models_to_test:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={gemini_key}"
    try:
        r = client.post(url, json={"contents": [{"parts": [{"text": "say hi"}]}]})
        print(f"Model {m}: status {r.status_code}")
        if r.status_code == 200:
            print(f"  Response: {r.json()['candidates'][0]['content']['parts'][0]['text'][:60]}")
    except Exception as e:
        print(f"Model {m}: error {e}")

print("\n--- Testing Claude ---")
if anthropic_key:
    claude_models = ["claude-3-5-haiku-20241022", "claude-3-haiku-20240307", "claude-3-5-sonnet-20241022", "claude-3-sonnet-20240229"]
    for cm in claude_models:
        try:
            r = client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": anthropic_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": cm,
                    "max_tokens": 50,
                    "messages": [{"role": "user", "content": "say hi"}],
                },
            )
            print(f"Claude {cm}: status {r.status_code}")
            if r.status_code == 200:
                print(f"  Response: {r.json()['content'][0]['text'][:60]}")
        except Exception as e:
            print(f"Claude {cm}: error {e}")

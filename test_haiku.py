# ============================================================
# test_haiku.py -- one-off diagnostic (do NOT commit this file)
# Tests your Anthropic key and Claude Haiku 4.5 from your own PC.
#
# HOW TO RUN (Windows, VS Code terminal, PowerShell):
#   1. Save this file in C:\Projects\market-pulse-ai
#   2. In the terminal type:  $env:ANTHROPIC_API_KEY = "paste-your-key-here"
#      and press Enter (the key lives only in that terminal window)
#   3. Type:  python test_haiku.py   and press Enter
#   4. Copy everything it prints and send it to Claude
#
# Never paste your real key into a chat message.
# ============================================================

import os
import sys
import requests

key = os.environ.get("ANTHROPIC_API_KEY", "")
print("Key found:", "yes" if key else "NO -- set it first (step 2 above)")
if not key:
    sys.exit(1)

# Show hidden problems: stray spaces or line breaks around the key
print("Key length:", len(key), "| length after strip:", len(key.strip()))
print("Key starts with sk-ant-:", key.strip().startswith("sk-ant-"))

for model in ["claude-haiku-4-5", "claude-haiku-4-5-20251001"]:
    print("\n--- Testing model:", model, "---")
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": key.strip(),
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 20,
                "messages": [{"role": "user", "content": "Reply with the single word: ok"}],
            },
            timeout=30,
        )
        print("HTTP status:", resp.status_code)
        print("Request id:", resp.headers.get("request-id", "none"))
        print("Body:", resp.text[:400])
    except Exception as e:
        print("Request failed:", type(e).__name__, str(e)[:300])

print("\nDone. Send this output to Claude.")

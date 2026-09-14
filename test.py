import os

import httpx

MODEL = "openai/gpt-oss-120b"   # Groq 콘솔에서 확인한 이름으로

r = httpx.post(
    "http://localhost:8000/v1/chat/completions",
    headers={"Authorization": "Bearer " + os.environ["GROQ_API_KEY"]},
    json={
        "model": MODEL,
        "messages": [{"role": "user", "content": "hello"}],
    },
    timeout=60,
)
print(r.status_code)
print(r.text[:500])
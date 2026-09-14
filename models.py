import os

import httpx

r = httpx.get(
    "https://api.groq.com/openai/v1/models",
    headers={"Authorization": "Bearer " + os.environ["GROQ_API_KEY"]},
    timeout=30,
)
for m in r.json().get("data", []):
    print(m["id"])
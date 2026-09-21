"""Shared probe helpers. Kept separate so the Groq probe's behaviour is not changed by imports."""
from importlib import metadata

EXCERPT_CHARS = 300


def default_user_agent():
    # The proxy forwards to the upstream with httpx defaults, so the runner path is seen as this UA.
    return 'python-httpx/' + metadata.version('httpx')


def redact(text, api_key):
    return text.replace(api_key, '[REDACTED]') if api_key else text

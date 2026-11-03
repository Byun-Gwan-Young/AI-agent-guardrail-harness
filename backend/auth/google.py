import os

def verify_google_token(token: str) -> dict:
    # Lazy import keeps existing APIs available without optional login dependencies.
    from google.auth.transport import requests
    from google.oauth2 import id_token

    client_id = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    if not client_id:
        raise RuntimeError("GOOGLE_CLIENT_ID is not configured")

    return id_token.verify_oauth2_token(
        token,
        requests.Request(),
        client_id,
    )

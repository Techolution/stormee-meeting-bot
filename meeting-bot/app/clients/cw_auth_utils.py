import hashlib
import hmac
import os
import time

global_shared_secret = os.environ.get(
    "BACKEND_SHARED_SECRET"
)

def generate_backend_signature(
    user_id: str,
    shared_secret: str | None = None,
) -> tuple[str, str]:
    timestamp = int(time.time() * 1000)

    message = f'{timestamp}:{{"userId":"{user_id}"}}'
    if not shared_secret:
        shared_secret = global_shared_secret
    signature = hmac.new(
        (shared_secret or "").encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return signature, str(timestamp)

def generate_headers_with_signature() -> dict:
    signature, timestamp = generate_backend_signature(user_id="unknown")
    headers = {
        "x-signature": signature,
        "x-timestamp": timestamp
    }
    return headers
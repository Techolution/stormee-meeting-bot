import hashlib
import hmac
import os
import time
import logging
from typing import Any
import jwt

DEFAULT_USER_EMAIL = "appmod@techolution.com"
global_shared_secret = os.environ.get("BACKEND_SHARED_SECRET")

if not global_shared_secret:
    logging.warning("BACKEND_SHARED_SECRET is not set; signatures will use an empty secret.")

def generate_backend_signature(
    user_id: str | None = None,
    shared_secret: str | None = None,
) -> tuple[str, str]:
    """Create a backend HMAC signature with safe defaults.

    Raises:
        TypeError: If a supplied identifier or secret is not a string.
    """
    if user_id is None or not isinstance(user_id, str):
        user_id = "unknown"
    if not isinstance(shared_secret, (str, type(None))):
        raise TypeError("shared_secret must be a string or None")

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

def generate_headers_with_signature(user_id: str | None = None) -> dict[str, str]:
    """Return signed request headers, using a safe fallback user identifier."""
    signature, timestamp = generate_backend_signature(user_id=user_id)
    return {
        "x-signature": signature,
        "x-timestamp": timestamp,
    }

def generate_jwt(email: str | None = None, config: dict[str, Any] | None = None, secret: str | None = None) -> str:
    """
    Generates a JSON Web Token (JWT) with the provided payload.
    
    Args:
        email (str): Email ID of the user
        config (dict, optional): Overrides for expiration, algorithm, issuer, etc.
        secret (str, optional): The signing secret. Defaults to checking env variables.
    
    Returns:
        str: The encoded JWT.
    """
    # Default configuration matching the original setup
    cfg = {
        "expires_in_seconds": 2 * 24 * 60 * 60,  # 2 days
        "algorithm": "HS256",
        "issuer": "appsecauth-ai",
        "audience": "appsecauth-api",
        "subject": "load-test-user",
    }
    
    # Update defaults with any provided overrides, while rejecting malformed config.
    if config is not None:
        if not isinstance(config, dict):
            raise TypeError("config must be a dictionary or None")
        cfg.update(config)

    normalized_email = email.strip() if isinstance(email, str) else ""
    if not normalized_email:
        normalized_email = DEFAULT_USER_EMAIL
        logging.warning("JWT email missing or empty; using dummy user email")

    # Use provided secret or fallback to environment variables
    signing_secret = secret or os.getenv("JWT_SECRET")
    logging.info("JWT signing secret available: %s", bool(signing_secret))
    if not signing_secret:
        raise ValueError(
            "Signing secret must be provided either as an argument or via "
            "JWT_GENERATOR_SECRET, SECRET_KEY, or NEXTAUTH_SECRET environment variables."
        )

    if not isinstance(cfg["expires_in_seconds"], int) or cfg["expires_in_seconds"] <= 0:
        raise ValueError("expires_in_seconds must be a positive integer.")

    now = int(time.time())

    # Create a copy so we don't mutate the original dictionary
    jwt_payload = {
        "_id": "user_12345",
        "firstname": "John",
        "lastname": "Doe",
        "email": normalized_email,
        "status": "ACTIVE"
    }
    token_payload = jwt_payload.copy()
    
    # Add standard claims
    token_payload.update({
        "iat": now,
        "exp": now + cfg["expires_in_seconds"]
    })

    if cfg.get("issuer"):
        token_payload["iss"] = cfg["issuer"]
    if cfg.get("audience"):
        token_payload["aud"] = cfg["audience"]
    if cfg.get("subject"):
        token_payload["sub"] = cfg["subject"]

    try:
        token = jwt.encode(
            token_payload,
            signing_secret,
            algorithm=cfg["algorithm"],
        )
    except (TypeError, ValueError, jwt.PyJWTError) as exc:
        logging.error("JWT generation failed for email=%s: %s", normalized_email, exc)
        raise RuntimeError("Unable to generate JWT") from exc

    logging.info("JWT generation completed: success=True")
    return token

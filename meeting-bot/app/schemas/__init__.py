"""API and wire contracts.

Two kinds of model live here, and they are deliberately separate:

  * HTTP request/response models (``meeting``, ``recording``, ``transcription``,
    ``status``) — the contract with our own callers.
  * Audio-service wire models (``websocket``) — the contract with a service we
    do not control.

Domain objects live with their domain package (``app.recording.models``,
``app.transcription.models``, …). Keeping them apart means an API change never
forces a domain change, and vice versa.
"""

from app.schemas.common import ErrorResponse, MessageResponse

__all__ = ["ErrorResponse", "MessageResponse"]

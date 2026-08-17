"""Meeting bot.

A service that sends a headless browser into a video meeting, records its
audio, and produces a transcript.

Architecture, in one paragraph: the API layer translates HTTP into calls on
``MeetingManager``, which owns a ``MeetingSession`` per meeting. A session
composes a browser, a meeting platform, a recorder and a transcription provider
— each behind an interface — and coordinates them. Anything crossing the network
goes through a client in ``app.clients``. Configuration, logging, correlation
and errors live in ``app.core``, which nothing in the domain may import *from*.

Dependencies point inward. ``app.core`` imports nothing from the domain;
``app.meeting`` names no concrete platform, transport or storage. The only
module that knows which implementation satisfies which interface is
``app.bootstrap``.

See ``docs/ARCHITECTURE.md`` for the full picture.
"""

from app.core.version import SERVICE_NAME, VERSION

__all__ = ["SERVICE_NAME", "VERSION"]

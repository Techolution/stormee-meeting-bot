"""Meeting context accumulation.

A deliberately narrow interface so the storage behind it can change — in-memory
now, Redis when context must outlive the pod — without touching any caller.

**Currently write-only.** Transcript segments are appended by
:meth:`~app.meeting.meeting_session.MeetingSession._handle_transcript_segment`
and nothing reads them back yet; the live transcript is served from the
transcription provider instead. This is staged infrastructure for the point at
which context must outlive a pod or be shared with another service — not a
wiring bug, and not a consumer someone forgot to connect. See
``docs/adr/0002-interfaces-from-day-one.md``.
"""

from app.context.buffer import ContextBuffer, InMemoryContextBuffer
from app.context.models import ContextItem, ContextQuery

__all__ = ["ContextBuffer", "ContextItem", "ContextQuery", "InMemoryContextBuffer"]

# 5. Captions use the latest visible snapshot

**Status:** Accepted (legacy-compatible trial)

## Context

Google Meet rewrites the caption rows currently visible on screen. Appending
every one-second poll produces many growing versions of the same sentence.

## Decision

Match the legacy bot exactly: each poll replaces the live caption buffer with
the current ordered DOM rows. No transcript segments are emitted while polling.
When transcription stops, the final visible snapshot is returned after removing
adjacent entries whose text is exactly identical.

## Consequences

- Growing partial captions do not accumulate across polls.
- Repeated speaker turns remain separate because DOM row order is preserved.
- Captions that scroll off screen before transcription stops are intentionally
  lost. The result is the latest visible caption window, not the whole meeting.
- The context buffer receives that same final snapshot at stop time.

This behavior intentionally mirrors
`legacy/services/stormee_meet_bot_service.py`.

# 3. Two upload transports behind one interface

**Status:** Accepted

## Context

[ADR 1](0001-client-only-websocket.md) removed the Socket.IO server, but the
ingest logic it contained was working code that had been debugged against real
GCS behaviour — resumable block sizing, `Content-Range` accounting, the
difference between a 308 and a 200. Discarding it would have thrown away the
expensive part.

Meanwhile the bot needed to remain runnable without the audio service: for local
development, for the test suite, and for any deployment where standing up a
second service is not worth it.

## Decision

Two implementations of `ChunkUploader`:

- `StreamingChunkUploader` — sends chunks to the audio service, buffers across
  disconnects, replays in order on reconnect. The audio service closes the object.
- `DirectChunkUploader` — performs the resumable upload from this process,
  sequencing chunks and accumulating 256 KiB blocks itself.

`RECORDING_UPLOAD_TRANSPORT` selects between them. `websocket` falls back to
`direct` when `WEBSOCKET_URL` is unset, with a warning — a bot that records into a
void is worse than one that takes a different route.

`Recorder` never branches on transport.

## Consequences

- The bot works with or without the audio service, unchanged.
- The GCS protocol knowledge is preserved and directly tested, without a network.
- Two paths to maintain, and only one is exercised in a given deployment. The
  test suite covers both to compensate.
- The two have genuinely different failure modes: streaming can buffer and retry
  indefinitely, while direct upload must retry the *same bytes at the same
  offset* because the resumable protocol permits nothing else. This is the main
  reason they are separate classes rather than a flag.

## What would change our mind

If the audio service became mandatory in every environment, `direct` would be
dead weight. It is one class behind an interface, so removing it is contained.

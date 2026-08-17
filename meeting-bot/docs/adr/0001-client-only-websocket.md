# 1. The bot is a WebSocket client, never a server

**Status:** Accepted

## Context

The previous implementation hosted a Socket.IO *server* in `main.py` and also
connected to `WEBSOCKET_URL` as a *client*. In practice `WEBSOCKET_URL` pointed
at the same mount path the process itself served, so a bot pod frequently talked
to itself over the network.

The server half was substantial: it handled `audioChunk` and `recordingEnded`,
buffered out-of-order chunks, drove GCS resumable uploads, confirmed uploads with
CW, and triggered artifact generation and email — roughly 600 lines of ingest
logic living inside the process that was supposed to be sitting in a meeting.

That arrangement had three costs. The pod's memory was shared between Chromium
and an upload buffer. Ingest could not be scaled or restarted independently of
meetings. And the process had two unrelated reasons to change.

An audio service is deployed separately and owns ingest.

## Decision

This codebase is a **client only**. There is no Socket.IO server in it.

The ingest logic was not deleted. It became the `direct` upload transport
(`recording/chunk_uploader.py` plus `clients/object_storage.py`), so a deployment
with no audio service still records successfully.

`app/clients/audio_service.py` describes *what* the bot says to the audio service;
`app/websocket/` owns *how* the connection is maintained. The two change for
different reasons.

## Consequences

- A bot pod's memory is Chromium's, not Chromium's plus an ingest buffer.
- Ingest scales and restarts independently of meetings.
- The audio-service protocol is a contract in one file rather than an
  implementation detail spread across a server.
- The bot remains runnable standalone, which keeps the test suite and local
  development free of a second service.
- The audio service's behaviour is now outside this repository. `recordingEnded`
  returning a poor acknowledgement is diagnosed elsewhere.

## What would change our mind

If the audio service were retired and ingest moved permanently into the bot,
`direct` would become the only transport and `websocket/` could go. The interface
split means that is a deletion, not a rewrite.

# Meeting and session identifier lifecycle

## Final contract

| Identifier | Created or accepted at | Requirement | Purpose |
| --- | --- | --- | --- |
| `sessionId` | Join/create session | Optional; generated when omitted | One live bot attendance |
| `meetingId` | Start recording | Optional; generated when omitted | One recording/meeting artifact |

Join does not accept or return `meetingId`. A meeting ID has no recording to identify at that point.

Generated examples:

```text
sessionId: abc-defg-hij_6e16ac69fc014df2a7711d071a32fe09
meetingId: abc-defg-hij_20260917T143045123456IST
```

## Direct worker flow

Join accepts the meeting URL and optional attendance ID:

```json
{
  "meetingUrl": "https://meet.google.com/abc-defg-hij",
  "sessionId": "abc-defg-hij_6e16ac69fc014df2a7711d071a32fe09"
}
```

Start recording requires that existing session and accepts an optional meeting ID:

```json
{
  "sessionId": "abc-defg-hij_6e16ac69fc014df2a7711d071a32fe09",
  "meetingId": "abc-defg-hij_20260917T143045123456IST"
}
```

- Unknown `sessionId` returns the typed not-found error before recording starts.
- A supplied `meetingId` is preserved.
- An omitted `meetingId` is generated from the meeting code and current IST time, including microseconds.
- The response returns both IDs and `recordingCount`.
- Stop and recording status use the returned `meetingId`.
- Leave, live status, audio, mute, and unmute use `sessionId`.

## Handler flow

The handler carries session identity in the path:

```text
POST /bot-sessions/{session_id}/recording/start
```

Its optional body is:

```json
{
  "meeting_id": "abc-defg-hij_20260917T143045123456IST"
}
```

The handler resolves `{session_id}`, resolves its assigned pod, and sends the worker `sessionId` plus the optional `meetingId`. It stores the returned meeting ID on the recording record and uses that record for later stop/status calls. An absent handler session returns `session_not_found`.

For sequential recordings, `sessionId` stays stable. If `meetingId` is omitted for each start, each recording receives a newly generated meeting ID. `recordingCount` is display-only.

## Internal name

`recording_meeting_id` is an internal Python parameter, not a third public identifier:

```text
sessionId + optional meetingId
  -> MeetingManager.start_recording
  -> MeetingSession.start_recording(recording_meeting_id=selected_meeting_id)
  -> RecordingContext.meeting_id
```

## Implementation references

- Schemas and Swagger: [`meeting-bot/app/schemas/meeting.py`](../meeting-bot/app/schemas/meeting.py), [`meeting-bot/app/schemas/recording.py`](../meeting-bot/app/schemas/recording.py), [`meeting-bot-handler/app/schemas/bot.py`](../meeting-bot-handler/app/schemas/bot.py)
- Worker routes and lookup: [`meeting-bot/app/api/routes/meeting.py`](../meeting-bot/app/api/routes/meeting.py), [`meeting-bot/app/api/routes/recording.py`](../meeting-bot/app/api/routes/recording.py), [`meeting-bot/app/meeting/meeting_manager.py`](../meeting-bot/app/meeting/meeting_manager.py)
- Handler route and orchestration: [`meeting-bot-handler/app/api/routes/bot.py`](../meeting-bot-handler/app/api/routes/bot.py), [`meeting-bot-handler/app/application/bot_handler.py`](../meeting-bot-handler/app/application/bot_handler.py)
- Handler-to-worker payload: [`meeting-bot-handler/app/clients/meeting_api.py`](../meeting-bot-handler/app/clients/meeting_api.py)
- Full per-file audit: [Identifier change file guide](identifier-change-file-guide.md)

## Storage limitation

The handler still uses `InMemorySessionRepository`. Its session-to-recording-to-pod mapping is process-local and is lost on restart. Multiple handler replicas require a shared repository; this is separate from the corrected HTTP contract.

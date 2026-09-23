# Identifier change: per-file implementation guide

This document maps the `sessionId`/`meetingId` correction to every currently changed file. It is a review companion to [Meeting and session identifier lifecycle](meeting-identifiers.md), which remains the source of truth for the public contract.

## Contract in one page

| Identifier | Meaning | Default format | Used for |
| --- | --- | --- | --- |
| `sessionId` | One continuous bot attendance | `<meeting-code>_<uuid>` | Join correlation, live status, leave, mute/unmute, audio, pod recovery |
| `meetingId` | Meeting and recording correlation | `<meeting-code>_<IST date-time>` | Recording start/stop/status, transcript and downstream recording attribution |

`sessionId` is optional at join/create time. `meetingId` is not accepted during join; it is optional at recording start. Supplied values are preserved and omitted values are generated at their respective lifecycle boundaries.

There is no third public recording identifier named `recordingMeetingId`. The internal Python parameter `recording_meeting_id` carries the same public `meetingId` into the recorder context.

## Flow-to-file map

| Flow stage | Primary files |
| --- | --- |
| Validate IDs at their lifecycle boundaries and expose Swagger examples | [`meeting-bot-handler/app/schemas/bot.py`](../meeting-bot-handler/app/schemas/bot.py), [`meeting-bot/app/schemas/meeting.py`](../meeting-bot/app/schemas/meeting.py), [`meeting-bot/app/schemas/recording.py`](../meeting-bot/app/schemas/recording.py) |
| Generate omitted IDs | [`meeting-bot-handler/app/api/routes/bot.py`](../meeting-bot-handler/app/api/routes/bot.py), [`meeting-bot/app/meeting/models.py`](../meeting-bot/app/meeting/models.py) |
| Store handler session and reject duplicates | [`meeting-bot-handler/app/domain/models.py`](../meeting-bot-handler/app/domain/models.py), [`meeting-bot-handler/app/application/session_service.py`](../meeting-bot-handler/app/application/session_service.py) |
| Send session ID on join and both IDs on recording start | [`meeting-bot-handler/app/application/bot_client.py`](../meeting-bot-handler/app/application/bot_client.py), [`meeting-bot-handler/app/clients/meeting_api.py`](../meeting-bot-handler/app/clients/meeting_api.py) |
| Register and resolve the live worker session | [`meeting-bot/app/api/routes/meeting.py`](../meeting-bot/app/api/routes/meeting.py), [`meeting-bot/app/meeting/meeting_manager.py`](../meeting-bot/app/meeting/meeting_manager.py), [`meeting-bot/app/runtime/session.py`](../meeting-bot/app/runtime/session.py) |
| Route later attendance commands to the correct pod/session | [`meeting-bot-handler/app/application/bot_handler.py`](../meeting-bot-handler/app/application/bot_handler.py), [`meeting-bot-handler/app/application/bot_service_resolver.py`](../meeting-bot-handler/app/application/bot_service_resolver.py) |
| Start and attribute recording by `meetingId` | [`meeting-bot/app/api/routes/recording.py`](../meeting-bot/app/api/routes/recording.py), [`meeting-bot/app/meeting/meeting_session.py`](../meeting-bot/app/meeting/meeting_session.py), [`meeting-bot/app/recording/models.py`](../meeting-bot/app/recording/models.py) |
| Verify the full contract | Handler and worker tests listed in [Tests](#tests) |

## Handler production files

### API and schemas

#### `meeting-bot-handler/app/schemas/bot.py`

- Makes `session_id` optional on session creation and defines an optional recording-start `meeting_id` body.
- Rejects empty supplied strings through `min_length=1`.
- Adds realistic Swagger examples for both formats.
- Adds `meeting_id` and `recording_count` to lifecycle action responses so recording start can return the correlation it actually used.

#### `meeting-bot-handler/app/api/routes/bot.py`

- Generates `sessionId` from the meeting code plus a UUID when omitted.
- Leaves `meetingId` unset until recording starts.
- Preserves a caller-provided session ID without rewriting it.
- Converts response timestamps to IST.
- Includes `meeting_id` and `recording_count` in recording-start responses.

### Application flow

#### `meeting-bot-handler/app/application/bot_client.py`

- Extends the join method to accept `session_id` and forwards it to the HTTP client.
- This is a pass-through layer; it does not generate or reinterpret either ID.

#### `meeting-bot-handler/app/clients/meeting_api.py`

- Sends only `sessionId` in the worker join payload.
- Sends required `sessionId` and optional `meetingId` in recording-start payloads.
- Changes leave, audio, mute, unmute, and worker status calls to use `sessionId`.
- Keeps recording stop/status keyed by `meetingId`; session-level transcription control uses the worker session correlation.
- This file is the clearest reference for the handler-to-worker wire contract.

#### `meeting-bot-handler/app/application/bot_handler.py`

- Saves the `sessionId` confirmed by the worker as `bot_session_id`.
- Uses the worker-confirmed session ID, with the handler session ID as a compatibility fallback, for live attendance commands and pod status.
- Starts recording with the worker session ID and optional caller meeting ID.
- Treats the worker's returned `meetingId` as authoritative recording attribution and saves it on `MeetingRecording`.
- Uses the active recording record's `meetingId` for stop and status calls.
- Returns `session_id`, `meeting_id`, `recording_id`, and the session-scoped `recording_count` after recording starts.
- Finalizes an active recording before completing a leave operation.

#### `meeting-bot-handler/app/application/bot_service_resolver.py`

- Recovers a pod by worker-confirmed `sessionId`, falling back to the handler `sessionId`.
- It no longer searches for a live attendance using `meetingId`.

#### `meeting-bot-handler/app/application/session_service.py`

- Rejects duplicate session IDs at creation; meeting IDs do not exist yet.
- Allows the worker-returned `meetingId` to be stored on each recording record.
- Maintains the relationship between recording records and their owning handler session.
- Stores the worker-confirmed meeting ID on the recording take and as the session's latest meeting ID.

### Domain and storage boundary

#### `meeting-bot-handler/app/domain/models.py`

- Keeps both `session_id` and `meeting_id` on `BotSession`.
- Keeps `bot_session_id` and pod assignment as internal routing state.
- Keeps `session_id` and `meeting_id` on every `MeetingRecording`.
- Formats exposed timestamps in IST.
- Clarifies that durability depends on the selected repository implementation.

#### `meeting-bot-handler/app/repositories/session_repository.py`

- Clarifies that this is a storage interface, not a guarantee that every implementation is durable.
- Its methods already cover lookup by both IDs and storage of recordings/events.

#### `meeting-bot-handler/app/bootstrap.py`

- Documents that the default `InMemorySessionRepository` is process-local.
- No shared database repository was added by this change.
- This remains the production limitation for restart recovery and multiple handler replicas.

### Time and logs

#### `meeting-bot-handler/app/core/time.py`

- Adds shared `Asia/Kolkata` conversion helpers used by generated IDs and user-visible timestamps.

#### `meeting-bot-handler/app/core/logging.py`

- Formats handler log timestamps in IST independently of the container timezone.
- This is operational support, not part of ID routing.

## Worker production files

### Join and attendance flow

#### `meeting-bot/app/schemas/meeting.py`

- Accepts optional `sessionId` on join and does not accept `meetingId`.
- Returns only `sessionId` from join.
- Changes attendance action payloads and responses to `sessionId`.
- Adds Swagger request and field examples.

#### `meeting-bot/app/api/routes/meeting.py`

- Passes the optional session ID into `MeetingRequest.build()`.
- Returns the final values accepted/generated by the worker.
- Uses `sessionId` for leave, audio, mute, and unmute.

#### `meeting-bot/app/meeting/models.py`

- Adds `session_id` to the immutable meeting request.
- Generates `<meeting-code>_<uuid>` for an omitted session ID.
- Generates `<meeting-code>_<IST date-time with microseconds>IST` for an omitted meeting ID.
- Preserves caller-supplied IDs.
- Copies the session ID and the recording-time meeting ID into recording context.
- Contains `new_recording_meeting_id()`, which currently delegates to the same meeting-ID generator and is not a separate public identity.

#### `meeting-bot/app/meeting/meeting_manager.py`

- Resolves live attendance by exact `sessionId`; it no longer guesses the only active session.
- Rejects duplicate active IDs instead of silently suffixing a caller value.
- Uses `sessionId` in attendance lifecycle logging context.
- Requires the submitted `sessionId` before selecting or generating a recording meeting ID.
- Returns the `meetingId` used by `MeetingSession.start_recording()` to the route.

#### `meeting-bot/app/runtime/session.py`

- Changes reservation behavior from “silently create a suffixed ID” to “reserve the exact ID or reject the duplicate.”
- This ensures a caller-provided identity remains stable and observable across services.

### Worker recording flow

#### `meeting-bot/app/schemas/recording.py`

- Requires `sessionId` and makes `meetingId` optional for start; stop still requires the returned `meetingId`.
- Adds complete Swagger examples.
- Adds a start response containing `meetingId`, `sessionId`, and `recordingCount`.

#### `meeting-bot/app/api/routes/recording.py`

- Sends the required `sessionId` and optional `meetingId` to the manager.
- Returns the actual recording context's `meetingId`, the owning `sessionId`, and the visual recording count.
- Uses the recorder context's ID in status responses.
- Converts recording timestamps to IST.

#### `meeting-bot/app/meeting/meeting_session.py`

- Uses the join request's `sessionId` instead of generating a second worker-only value.
- Tracks how many recordings have started during the live session.
- Carries the recording endpoint's `meetingId` into `RecordingContext` through the internal `recording_meeting_id` parameter.
- Returns that same `meetingId` after recording starts.
- Uses the recorder context ID for recording-ended events and transcript segments while a recorder is active.

`recording_meeting_id` is an internal disambiguating parameter name only. In the current path:

```text
POST /recordings/start meetingId
  -> MeetingManager.start_recording(meeting_id)
  -> MeetingSession.start_recording(recording_meeting_id=meeting_id)
  -> RecordingContext.meeting_id
```

It does not introduce a third ID or an HTTP field. It carries the caller-provided or newly generated recording meeting ID after the session lookup succeeds.

#### `meeting-bot/app/recording/models.py`

- Adds `session_id` to `RecordingContext` so downstream processing can retain both correlations.

### Transcription, time, and logs

#### `meeting-bot/app/api/routes/transcription.py`

- Converts chat timestamps to IST.
- The existing worker transcription wire shape still names its field `meetingId`, but the handler supplies the worker session value so lookup remains session-scoped; active transcript segments are attributed to the recorder context's meeting ID.

#### `meeting-bot/app/core/time.py`

- Adds the shared worker-side IST conversion helpers.

#### `meeting-bot/app/core/logging.py`

- Formats worker text and JSON log timestamps in IST.
- This supports cross-service tracing but does not choose which ID routes an operation.

## Tests

### Handler tests

#### `meeting-bot-handler/tests/conftest.py`

- Updates the fake worker to accept, return, and independently track both IDs.
- Validates recording requests against `meetingId` and attendance status against `sessionId`.
- Returns the expanded recording-start response used by production code.

#### `meeting-bot-handler/tests/unit/clients/test_meeting_api.py`

- Verifies that join sends only camelCase `sessionId`.
- Verifies recording start sends `sessionId` and optional `meetingId`.
- Updates error and request-ID tests for the new method signature.

#### `meeting-bot-handler/tests/unit/application/test_bot_handler.py`

- Verifies the worker-confirmed session ID is stored.
- Verifies recording responses include session ID and count.
- Verifies sequential generated recordings receive distinct meeting IDs and increment the visual count.
- Updates pod recovery coverage to search by session ID.

#### `meeting-bot-handler/tests/integration/test_bot_session_flow.py`

- Verifies caller-provided session and recording meeting IDs at their separate boundaries.
- Verifies sequential generated recording starts keep the session correlation, create distinct meeting IDs, and increase `recording_count`.
- Updates generated-ID assertions.

### Worker tests

#### `meeting-bot/tests/unit/meeting/test_models.py`

- Verifies generated ID formats.
- Verifies caller-provided session IDs and recording-time meeting IDs are preserved.
- Verifies the recording meeting-ID generator uses the IST datetime format.

#### `meeting-bot/tests/integration/test_api.py`

- Updates join validation because only the session ID is optional there.
- Updates attendance action tests to send `sessionId` and recording tests to send `meetingId`.

#### `meeting-bot/tests/integration/test_meeting_session.py`

- Supplies explicit session IDs to fixtures.
- Verifies recording count behavior.
- Verifies sequential generated recordings receive distinct meeting IDs.

#### `meeting-bot/tests/unit/recording/test_upload_finalizer.py`

- Supplies the newly required recording-context session correlation in its fixture.

## Documentation files

#### `docs/meeting-identifiers.md`

- Defines the public contract, endpoint mapping, complete flow, storage limitation, examples, and links to implementation files.

#### `docs/identifier-change-file-guide.md`

- This file: maps the implementation and tests file by file.

#### `meeting-bot-handler/README.md`

- Clarifies that the default handler repository is process-local and single-replica.

#### `meeting-bot-handler/docs/API.md`

- Documents that only `meeting_url` is required at creation and omitted IDs are generated.
- Replaces inaccurate durability claims with repository-specific language.

#### `meeting-bot-handler/docs/ARCHITECTURE.md`

- Distinguishes handler control-plane state from worker runtime state.
- States that current handler state does not survive a handler restart.

## Changed files outside the identifier contract

These working-tree changes are present but are not required to implement the ID flow:

#### `meeting-bot/scripts/create_auth_profile_docker.sh`

- Increases the post-password Google login wait from 20 to 30 seconds.
- This is authentication timing and unrelated to session/meeting IDs.

#### `meeting-bot/tests/conftest.py`

- Adds a no-op `startup_mh_services()` method to `FakeCWClient` to mirror a production hook.
- This is test-double compatibility and unrelated to ID routing.

## Review findings and remaining limitations

1. The public two-ID contract is consistent across handler schemas, handler-to-worker transport, worker routes, recording responses, and tests.
2. `recording_meeting_id` is redundant terminology, not a distinct identity. Removing that parameter later would reduce confusion, but it does not currently change the value sent downstream.
3. The handler routing map remains in `InMemorySessionRepository`; restart recovery and multiple handler replicas require a shared repository.
4. The wider Meeting API may already persist `meetingId`, but this repository only proves that the worker reports lifecycle status to it. It does not prove persistence of the handler's session-to-pod mapping.
5. Timezone/logging changes support the requested IST display format but are broader than the core routing fix.

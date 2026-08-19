# Architecture

The handler is the control plane. It owns the durable state of a meeting and
decides which bot pod runs it. The bot pod owns the browser, the meeting, and
the audio.

```
   client (scheduler, Cloud Tasks, meeting API)
                    |
                    v
            API routes (thin)
                    |
                    v
              BotHandler ................. orchestration, idempotency
               /        \
              v          v
     SessionService    BotServiceResolver .. which pod?
          |                  |
          v                  v
   SessionRepository     BotPodPool ........ Kubernetes API + readiness probes
          |                  |
     durable state       BotClient
                             |
                             v
                    MeetingApiClient ....... the bot's wire contract
                             |
                             v
                     bot pod /api/meet
```

## Who owns what

| Layer | Knows about | Never touches |
|---|---|---|
| Routes | HTTP shapes | business rules |
| BotHandler | lifecycle, retries, state transitions | HTTP details, Kubernetes, SQL |
| SessionService | durable state and its transitions | HTTP, pods |
| BotServiceResolver / BotPodPool | pods, readiness | sessions' business meaning |
| BotClient / MeetingApiClient | URLs, payloads, error envelopes | state, storage |

The client never learns a pod name, pod IP, or internal URL. It holds a
`session_id`; the handler resolves everything behind it.

## Two kinds of status

**Durable** state lives here: `meeting_status`, `bot_status`,
`recording_status`, `transcription_status`, and their timestamps. It survives
the pod.

**Runtime** state lives on the pod: browser up, captions on, participant count.
`GET /bot-sessions/{id}/status` reads durable state and enriches it with runtime
state when the pod answers. A pod that cannot be reached degrades the response
rather than failing it.

An accepted command is not a completed one. `POST /meetings/join` returning 202
means STARTING, never RUNNING; a background watcher polls the pod and promotes
the session to ACTIVE only when the pod reports `in_meeting`.

## Current limitations

**Session state is in memory.** `InMemorySessionRepository` is the only
implementation; sessions do not survive a restart, and the handler must run as a
single replica. The seam is `SessionRepository` — a PostgreSQL implementation
drops in without touching the layers above. `BotServiceResolver.recover` already
exists for the restart case: it asks the cluster which pod holds a meeting.

**Locks are per-process.** `KeyedLock` serializes commands for one session
within one replica. Scaling out needs a database-level lock.

**Redis is unused.** `RedisRepository` is a stub. Heartbeats and worker
registries would live there; they are not needed while the pod's own `/ready`
and `/status` answer the same questions.

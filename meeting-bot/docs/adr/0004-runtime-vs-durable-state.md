# 4. Runtime and durable state are separate types

**Status:** Accepted

## Context

The previous implementation had one `MeetingState` enum covering both
`RECORDING_STARTED` and `PARTICIPANT_COUNT_CHANGED`, written to Redis, and
`MeetBot` instance attributes (`scraping_active`, `participant_count`,
`current_meeting_id`) that lived only in memory. Which was authoritative depended
on which you happened to read.

That distinction matters more than it appears, because the two answer different
questions and have different lifetimes. "Is the recorder running right now?" is
meaningless after a restart. "Did this meeting get recorded?" must survive one.

Conflating them produces a specific class of bug: a decision reads in-memory state,
behaves correctly, and then silently changes its answer after a pod restart.

## Decision

Two types, in two packages, with no shared vocabulary.

**`app/runtime/state.py` — `RuntimeState`.** In memory, dies with the process.
Per-component status (`browser`, `platform`, `recording`, `transcription`,
`websocket`), participant count, heartbeat. Read by `/status` and the probes.
Answers *should this pod be restarted?*

**`app/repositories/` — `MeetingStateRepository`.** Redis when available,
in-memory otherwise. Records coarse lifecycle transitions —
`joining`, `in_meeting`, `recording_started`, `left`. Answers *what happened to
this meeting?*

The enums are deliberately different. `ComponentState` has `degraded`, which is
meaningless durably. `MeetingLifecycleEvent` has `recording_stopped`, which is a
historical fact rather than a current condition.

## Consequences

- `/status` and `/meetings/{id}/state` return genuinely different things, and the
  API documents which is which.
- Losing Redis loses history, not correctness. Meetings run unaffected.
- Runtime state is free to read — no I/O — so probes can poll it as often as they
  like.
- Two things to update when a meaningful transition occurs. `MeetingSession`
  does both in one place (`_record_event`) to keep them from drifting.

## What would change our mind

If the upstream Meeting API became the sole system of record, `repositories/`
could collapse into a client call. The interface makes that a substitution.

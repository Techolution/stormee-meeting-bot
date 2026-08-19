# ADR 0002: Dispatch by allocating from a bot pod pool

## Context

The bot runs as a Deployment of interchangeable pods, each able to host one
meeting at a time. A meeting, once joined, is *not* interchangeable: the browser
session, the recording buffer and the transcript all live in one pod's memory.
Only that pod can stop that recording or report that meeting's status.

The handler therefore needs two things Kubernetes does not give it for free:
a way to pick a pod that is free, and a way to keep talking to that same pod
afterwards.

ADR 0001 assumed a Job per meeting, which would answer both — a Job the handler
created is a pod the handler knows. But it pays Chromium's startup on every join
(tens of seconds, in front of a waiting host), and needs a Service per session
to be addressable.

## Decision

Allocate from the running pool instead.

1. List the pods behind the bot Deployment through the Kubernetes API, filtered
   by label selector.
2. Probe each pod's `GET /api/meet/ready`. The bot already fails readiness while
   it is in a meeting, so this *is* the free/busy signal — no extra bookkeeping,
   and no state that can disagree with reality.
3. Join on the first pod that accepts, and record its address on the session.
4. Address that pod directly, by pod IP, for the rest of the session.

Readiness is treated as a hint rather than a claim. Between the probe and the
join another replica can take the pod; it answers `409 meeting_already_active`
and the handler moves to the next candidate. Only a pod that actually accepts
the join is written to the session.

## Consequences

The bot's load-balanced Service is unused for session commands — routing a
follow-up through it would reach a pod that never heard of the meeting. The
handler needs RBAC to list pods, which is the one new cluster dependency.

Pod IPs are ephemeral. A pod that dies takes its meeting with it; the assignment
becomes invalid and the session fails. `BotServiceResolver.recover` handles the
inverse case — the handler forgetting an assignment the cluster still has — by
asking each pod whether it holds the meeting.

`KubernetesJobManager` and `KubernetesServiceManager` remain unimplemented. A
Job per meeting is still the better answer if bots ever need per-meeting
isolation or wildly different resource shapes.

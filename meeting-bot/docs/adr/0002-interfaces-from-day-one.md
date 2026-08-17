# 2. Three interfaces exist before their second implementation

**Status:** Accepted

## Context

`MeetingPlatform`, `TranscriptionProvider` and `ContextBuffer` each have exactly
one implementation today. Introducing an interface for a single implementation is
usually premature — it adds indirection to buy flexibility nobody has asked for.

These three are different, because the second implementation is already visible:

- **Transcription.** Captions are a poor transcript source: no reliable timing, no
  diarisation, text that mutates while you read it. The recorded audio already
  exists, and running speech recognition over it is strictly better. This
  migration is planned, not hypothetical.
- **Meeting platform.** Teams and Zoom are recurring requests.
- **Context buffer.** In-memory context dies with the pod. The moment context must
  outlive a pod or be shared, it needs Redis.

The previous implementation had none of these. `MeetBot` scraped the caption DOM
directly, so moving to speech-to-text would have meant editing meeting lifecycle
code.

## Decision

Define all three interfaces now. Meeting code programs against them exclusively.

The cost is one file of abstract methods each, and a registry that maps a
configured name to a factory. The benefit is that each migration becomes a new
file plus a configuration change.

Everything else stays concrete. `Recorder`, `ChatMonitor`, `ParticipantMonitor`,
`Heartbeat` and the clients have no interface, because there is no second
implementation in view.

## Consequences

- Adding a platform is: implement the interface, call `register_platform`. No
  change to `meeting/`, `recording/` or `transcription/`.
- Moving to speech-to-text is: implement the interface, `register_provider`, set
  `TRANSCRIPTION_PROVIDER`.
- The test suite runs without a browser, because `MeetingPlatform` has a fake.
  That is a direct consequence, and arguably the largest immediate benefit.
- One extra indirection when reading a call path.

## What would change our mind

If speech-to-text were abandoned and no second platform materialised within a
year, `TranscriptionProvider` and the registry would be indirection without a
payer, and collapsing them would be reasonable. The fakes would have to be
replaced with something else first.

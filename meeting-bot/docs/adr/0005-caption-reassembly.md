# 5. Captions are reassembled, not accumulated

**Status:** Accepted

## Context

Google Meet's caption area is not a log. It renders two or three blocks, rewrites
them in place as a speaker continues, and drops them once they scroll away.
Polling it yields a stream of overlapping snapshots, not a sequence of utterances.

Both obvious readings fail:

- **Append every snapshot.** Each sentence appears once per poll — at a 1-second
  interval, a ten-second utterance appears ten times, growing.
- **Keep only the newest snapshot.** This is what the previous implementation did
  (`self.live_caption_buffer = current_snapshot`), with adjacent-duplicate removal
  at the end. The result was a "transcript" containing the last few seconds of
  visible captions and nothing else — a bug that produced plausible-looking output
  and therefore survived a long time.

## Decision

`CaptionAggregator` tracks each speaker's in-progress block across snapshots and
emits a segment when the block disappears.

Each new reading is merged into the text already held, handling the three ways
Meet rewrites a block:

| Case | Meaning | Action |
|---|---|---|
| `extension` | new text extends old | take the new text |
| `redraw` | new is a prefix of old, mid-re-render | keep the longer |
| `scroll` | Meet dropped the head of a long utterance | splice on the overlap |
| no overlap | the speaker began something new | emit the old segment |

The scroll case needs a minimum overlap (8 characters). Shorter matches are
coincidence — common words repeat — and splicing on them corrupts the text.

The aggregator is pure and synchronous. `CaptionTranscriptionProvider` owns the
polling loop; reading the DOM belongs to the platform. Three separable concerns,
each testable alone.

## Consequences

- Transcripts contain the whole meeting. **They will be substantially longer than
  before** — noted in [MIGRATION.md](../MIGRATION.md) because downstream consumers
  should expect it.
- A segment is emitted only when its utterance *completes*, so the sentence
  currently being spoken is not yet in the transcript. This is correct but
  occasionally surprising when watching a live transcript.
- The merge rules are heuristics over an undocumented, changing UI. They are the
  most heavily tested code here for that reason.

## What would change our mind

Speech-to-text over the recorded audio removes the problem entirely: real
timestamps, real diarisation, no mutation. When that provider lands, this becomes
a fallback rather than the primary path — which is exactly why
`TranscriptionProvider` exists ([ADR 2](0002-interfaces-from-day-one.md)).

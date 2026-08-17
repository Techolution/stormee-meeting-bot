# Testing

## Running

```bash
make test          # everything
make test-unit     # unit tests only
make coverage      # with an HTML report
make check         # lint + types + tests, as CI runs it
```

The suite runs in about four seconds and needs **no browser, no network, and no
Redis**. That is a property worth protecting: a suite that needs Chromium is a
suite people stop running.

```bash
.venv/bin/pytest tests/unit/transcription -v          # one area
.venv/bin/pytest -k caption                           # by name
.venv/bin/pytest tests/unit/recording/test_sequencer.py::test_duplicates_are_dropped_not_double_written
```

---

## Layout

```
tests/
├── conftest.py              fakes and builders shared by everything
├── unit/                    one module, no I/O
│   ├── core/                config, logging
│   ├── context/             the context buffer
│   ├── meeting/             lifecycle, chat, participants
│   ├── meeting_platform/    platform selection
│   ├── recording/           sequencing, buffering, upload, capture
│   ├── runtime/             runtime state, session registry
│   ├── transcription/       caption reassembly
│   └── websocket/           reconnection policy
└── integration/             components together
    ├── test_meeting_session.py   join → record → transcribe → leave
    └── test_api.py               the HTTP contract
```

---

## How it stays fast

Every collaborator a session reaches is behind an interface, so an integration
test can exercise the whole `join → record → transcribe → leave` flow against
fakes. That is the practical test of whether the abstractions are real: if a
session could only be tested with Chromium running, they would not be.

The fakes are in `tests/conftest.py`:

| Fake | Stands in for | Notable behaviour |
|---|---|---|
| `FakePlatform` | `MeetingPlatform` | Scriptable captions and chat; records what was clicked. |
| `FakeAudioService` | `AudioServiceClient` | **Raises `WebSocketNotConnectedError` when disconnected**, as the real transport does. |
| `FakeCWClient` | `CWUtilsClient` | Issues upload targets, records confirmations. |
| `FakeStorage` | `ResumableUploadClient` | Records every block and its bytes. |

**Fakes must be faithful to the contract they replace.** `FakeAudioService`
originally accepted sends while disconnected, which made a buffering test pass
that should have failed. A fake that is more permissive than the real thing hides
exactly the behaviour it exists to test.

---

## Conventions

**A test name states the behaviour, not the method.**

```python
def test_out_of_order_chunk_is_held_until_the_gap_fills(): ...
def test_a_brief_dip_to_one_does_not_trigger_a_leave(): ...
def test_reserved_field_names_do_not_raise(): ...
```

Not `test_accept()`, `test_monitor()`, `test_logging()`.

**Where a test encodes a non-obvious rule, the docstring says why.**

```python
def test_a_brief_dip_to_one_does_not_trigger_a_leave() -> None:
    """This is the case a naive check gets wrong: reconnects look like an empty room."""
```

**Wait on a condition, never on a fixed sleep.**

```python
await wait_for(lambda: platform.captions_consumed >= 4)   # yes
await asyncio.sleep(0.2)                                   # no
```

A sleep long enough to be reliable is long enough to make the suite slow; one
short enough to be fast is flaky under load. `wait_for` is in `conftest.py`.

**Test timings come from the `settings` fixture.** It overrides poll intervals and
grace periods so tests are fast, and clears the developer's own environment so a
local `.env` cannot change an outcome.

**Warnings are errors** (`filterwarnings = ["error"]`). An unawaited coroutine or
a deprecation is a failure, not a line of scrollback.

---

## What is covered, and why those things

Coverage percentage is not the target; the risk-weighted areas are.

| Area | Why it is tested heavily |
|---|---|
| `CaptionAggregator` | The most subtle logic here, and a regression is invisible by inspection — a wrong transcript still looks like a transcript. |
| `ChunkSequencer` | Out-of-order writes make a recording *unplayable*, not merely scrambled. |
| `AudioBuffer` | The bound is what stops a network outage becoming an OOM kill. |
| `ChunkUploader` | Both transports, including partial failure and interrupted drains. |
| `LifecycleRunner` | Shutdown ordering is what protects the recording. |
| `ParticipantMonitor` | Getting the grace period wrong abandons live meetings. |
| `AudioCapture` | Must never raise — an exception reaches page JS and stops the recorder. |
| `core/logging` | A reserved-field collision crashed the upload path in practice. |
| API contract | Status codes and the error envelope are what callers depend on. |

---

## Adding a test

Put it in `unit/` if it exercises one module with no I/O; `integration/` if it
crosses component boundaries.

For a new module, ask what its failure would cost. `CaptionAggregator` gets eleven
tests because a bad transcript is silently wrong; `templates.py` gets none of its
own because a malformed email is obvious and harmless.

If a test needs a new collaborator, add a fake to `conftest.py` rather than a
mock. A fake with real behaviour catches contract violations; a mock asserts that
a call was made, which is a weaker claim.

---

## Not covered by this suite

Deliberately, because it needs a real browser and a real meeting:

- Google Meet DOM selectors actually matching the live UI.
- The browser-side JavaScript audio pipeline.
- Playwright launch behaviour inside a container.

Selectors are the part most likely to break, and only a real meeting will tell
you. Before releasing a change to `meeting_platform/google_meet/`, run through
[SETUP.md](SETUP.md#joining-your-first-meeting) against a live meeting with
`make run-headful`.

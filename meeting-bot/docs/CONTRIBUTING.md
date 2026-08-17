# Contributing

## Before you push

```bash
make check    # lint, types, tests — all three must pass
```

CI runs exactly this.

---

## Where new code goes

The [dependency rule](ARCHITECTURE.md#the-one-rule) decides. Work outward from
what the code *is*:

| The code… | Belongs in |
|---|---|
| translates HTTP | `api/` |
| decides what happens and in what order | `meeting/` |
| drives Chromium | `browser/` |
| knows a Google Meet selector or flow | `meeting_platform/google_meet/` |
| moves audio from the page to storage | `recording/` |
| turns something into transcript | `transcription/` |
| maintains the audio-service connection | `websocket/` |
| calls an external HTTP API | `clients/` |
| is config, logging, correlation, errors, timing | `core/` |

Two rules that are not negotiable, because breaking either has already caused a
bug here:

- **`core/` imports nothing from the domain.** Configuration and logging cannot
  develop opinions about meetings.
- **A client never imports a domain model.** Serialise on the domain side
  (`AudioChunk.as_wire_payload()`) and hand the client the result. Importing a
  domain model into `clients/` produced an import cycle during development.

If a change requires editing `meeting/` *and* `meeting_platform/` *and*
`recording/`, the abstraction between them is probably wrong. Say so in the PR
rather than working around it.

---

## Finding your way around

If you cannot work out what calls something, check
[ENTRY_POINTS.md](ENTRY_POINTS.md) before assuming it is dead. About twenty
methods here are reached only through a callback, a socket event, a chat command,
or a timer, and each carries a `Called by:` docstring line.

When you add another such method, add both: the `Called by:` line, and a row in
that document.

---

## Style

**Match the surrounding code.** Comment density, naming, and structure should be
indistinguishable from the file you are editing.

**Comments explain *why*, never *what*.** The code says what it does.

```python
# Yes — the reason is not recoverable from the code:
# Meet hides its toolbars after a few idle seconds and the buttons become
# genuinely unclickable. Every interaction with a toolbar control needs this.
await self._browser.wake_controls()

# No:
# Move the mouse
await self._browser.wake_controls()
```

**Every module has a docstring saying what it owns and what it must not do.**
That constraint is what keeps the layering real; a module without one drifts.

**Every `except Exception` carries a reason.**

```python
except Exception as error:  # noqa: BLE001 - must not reach page JavaScript
```

`BLE001` is enabled precisely so this is a deliberate act.

**Constants are named and commented where the value is not obvious.**

```python
#: GCS requires every non-final resumable block to be a multiple of 256 KiB.
_BLOCK_SIZE = 256 * 1024
```

**Never call `os.getenv`.** Add the setting to `core/config.py` and inject it.

**Never call `asyncio.create_task` directly.** Use a `TaskSupervisor` — see
[ARCHITECTURE.md](ARCHITECTURE.md#concurrency-and-background-work) for the two
failure modes it prevents.

---

## Errors

New failure modes get a typed exception in `core/exceptions.py` with a status and
a stable `code`. Do not raise `HTTPException` from a route — translation happens
in one place, `api/errors.py`, which is why routes have no `try`/`except`.

Choose deliberately between failing and degrading:

- **Fail** when the caller asked for something specific and it did not happen.
- **Degrade** when the meeting can continue usefully without it — a dropped
  audio-service connection, an unreachable Redis, a failed notification email.

When you degrade, log at `WARNING` with the reason. Silent degradation is the
hardest kind of problem to diagnose.

---

## Logging

```python
logger.info(
    "Recording stopped",
    extra={"meeting_id": meeting_id, "chunks_uploaded": 120, "bytes": 8912896},
)
```

- A short, constant message. Variables go in `extra`, not in an f-string, so logs
  are searchable and aggregatable.
- `meeting_id`, `session_id` and `request_id` are attached automatically inside a
  bound context — do not pass them by hand.
- Field names must not collide with `LogRecord` attributes (`filename`, `module`,
  `name`, `args`, `message`, …). `SafeLogger` renames collisions rather than
  crashing, but a renamed field reads badly. See
  `_STANDARD_RECORD_FIELDS` in `core/logging.py`.

---

## Tests

See [TESTING.md](TESTING.md). In short: name the behaviour, wait on conditions
rather than sleeps, and prefer a faithful fake to a mock.

If you fix a bug, add the test that would have caught it — and check that it
fails without your fix. Every bug in
[MIGRATION.md](MIGRATION.md#bugs-fixed) has one.

---

## Changing Google Meet selectors

Meet changes without notice, and its class names are obfuscated build artifacts.

1. All selectors live in `meeting_platform/google_meet/selectors.py`. Add nothing
   inline.
2. Prefer accessibility attributes (`aria-label`, roles). They track the visible
   UI and survive rebuilds; `.KJktIb` does not.
3. Where a class name is unavoidable, put it *behind* the accessible selector in
   the candidate list and comment what it was and when.
4. Verify against a live meeting — the test suite cannot check this. Use
   `make run-headful` and set `BROWSER_SCREENSHOT_DIR`.

---

## Changing the browser-side JavaScript

`meeting_platform/google_meet/scripts/*.js` runs inside the page. It is the part
most sensitive to browser behaviour and the hardest to debug.

- Test against a real meeting. Nothing else exercises it.
- Keep it defensive: a `null` element must not throw, because an exception in a
  page callback can stop the recorder.
- `audio_pipeline.js` and `stealth.js` are init scripts and must run before the
  first navigation — that is why they are registered by `BrowserManager`.

---

## Pull requests

State the behaviour change, not the file list. A reviewer can read the diff; what
they cannot recover is what you decided and why.

Worth calling out explicitly:

- A new setting, and its default.
- A change to shutdown ordering or timeouts.
- Anything that alters what happens to audio on a failure.
- A new external call, and what happens when it fails.

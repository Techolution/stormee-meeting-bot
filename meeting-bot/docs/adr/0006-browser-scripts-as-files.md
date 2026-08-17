# 6. Browser JavaScript lives in `.js` files

**Status:** Accepted

## Context

The previous implementation kept about 1,100 lines of browser-side JavaScript in
Python string literals (`js_helpers.py`), with more inline at call sites for
things like reading the chat panel and detecting the room state.

Embedded in a Python string, JavaScript gets no syntax highlighting, no linting,
no editor support, and inherits Python's escaping rules on top of its own. A diff
touching it is unreadable. And the code in question — a WebRTC audio graph and a
`MediaRecorder` pipeline — is the most browser-sensitive and hardest-to-debug part
of the system.

## Decision

Browser scripts are real `.js` files under
`meeting_platform/google_meet/scripts/`, loaded from disk and cached at first use.

The four large scripts were extracted **verbatim** — programmatically, not
retyped. This part is the most sensitive to browser behaviour, and rewriting it
during a restructuring would have made any resulting bug impossible to attribute
to either the move or the rewrite. Inline snippets were extracted into the same
directory and given JSDoc.

Where a script needs selectors, they are passed in as an argument so that
`selectors.py` remains the single source of DOM knowledge:

```python
await browser.try_evaluate(room_state_script, {
    "lobbySelectors": list(selectors.LOBBY_INDICATORS),
    "inMeetingSelectors": list(selectors.IN_MEETING_INDICATORS),
})
```

`bootstrap.py` verifies the scripts are present at startup, so a packaging
mistake fails immediately rather than at the first join.

## Consequences

- The JavaScript is editable, lintable, and reviewable as JavaScript.
- `platform.py` reads as flow control rather than as a wall of quoted text.
- Scripts must be shipped with the package. `pyproject.toml` declares them as
  package data — without that they are absent from a wheel and every join fails,
  which is precisely why the startup check exists.
- Two languages in one package, and a reader must follow one more hop to see what
  a script does. The JSDoc on each is there to make that hop worthwhile.

## What would change our mind

Nothing foreseeable. The alternative is worse in every respect that matters.

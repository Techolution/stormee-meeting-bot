"""Browser-side JavaScript, loaded from disk.

These scripts run inside the Meet page, not in Python. Keeping them as ``.js``
files rather than embedded string literals means editors highlight and lint
them, diffs are readable, and no Python quoting rules apply to JavaScript.

Scripts are read once at import and cached, so page evaluation never pays for
file I/O.

Layout:
  ``audio_pipeline.js``  Installs the virtual microphone and taps remote WebRTC
                         audio. Must run as an init script, before Meet's own
                         code calls ``getUserMedia``.
  ``stealth.js``         Hides ``navigator.webdriver``. Also an init script.
  ``recorder_start.js``  Starts a ``MediaRecorder`` over the mixed audio graph
                         and pushes chunks to Python. Called with a meeting id
                         and the timeslice to chunk at.
  ``recorder_stop.js``   Stops the recorder and flushes the final chunk.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

_SCRIPT_DIR = Path(__file__).parent


@cache
def load_script(name: str) -> str:
    """Read a script by filename, caching the result.

    Raises:
        FileNotFoundError: If the script is missing — a packaging error worth
            failing loudly at startup rather than silently at join time.
    """
    path = _SCRIPT_DIR / name
    if not path.is_file():
        raise FileNotFoundError(f"browser script not found: {path}")
    return path.read_text(encoding="utf-8")


def audio_pipeline() -> str:
    """Init script: virtual microphone plus remote-audio capture."""
    return load_script("audio_pipeline.js")


def stealth() -> str:
    """Init script: mask automation fingerprints."""
    return load_script("stealth.js")


def recorder_start() -> str:
    """Page function ``async ({meetingId, chunkDurationMs}) => …`` that starts recording."""
    return load_script("recorder_start.js")


def recorder_stop() -> str:
    """Page function ``async () => …`` that stops recording and flushes."""
    return load_script("recorder_stop.js")


def init_scripts() -> tuple[str, ...]:
    """Scripts that must be registered before the first navigation, in order."""
    return (stealth(), audio_pipeline())


__all__ = [
    "audio_pipeline",
    "init_scripts",
    "load_script",
    "recorder_start",
    "recorder_stop",
    "stealth",
]

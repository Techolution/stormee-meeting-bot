"""Google Meet DOM selectors, in one place.

Meet ships UI changes without notice and its class names are obfuscated build
artifacts. When a flow breaks, the fix is almost always a selector — so every
selector lives here, named for intent, rather than being scattered through the
code that uses it.

Two conventions:

  * Prefer accessibility attributes (``aria-label``, roles) over class names.
    They track the visible UI and survive rebuilds; ``.KJktIb`` does not.
  * Where a class name is unavoidable, keep it in a fallback list *behind* the
    accessible selector and comment what it was at the time of writing.

Selector groups are exposed as tuples so callers can try them in priority order.
"""

from __future__ import annotations

from typing import Final

# --------------------------------------------------------------------------
# Pre-join / lobby
# --------------------------------------------------------------------------

#: The "Sign in with your Google account" interstitial and its dismiss button.
SIGN_IN_POPUP_DISMISS: Final[tuple[str, ...]] = (
    'button[jsname="EszDEe"]',
    ".KJktIb button:has-text('Got it')",
    'button:has-text("Got it")',
)

#: Container of the sign-in interstitial, removed outright when the button misses.
SIGN_IN_POPUP_CONTAINER: Final[str] = ".KJktIb"

#: Guest name field on the pre-join screen.
GUEST_NAME_INPUT: Final[tuple[str, ...]] = (
    'input[aria-label="Your name"]',
    'input[placeholder="Your name"]',
    'input[jsname="YPqjbf"]',
)

#: Buttons that submit a join request. "Ask to join" appears for guests,
#: "Join now" for admitted accounts, "Switch here" when already joined elsewhere.
JOIN_BUTTONS: Final[tuple[str, ...]] = (
    'button[aria-label*="Ask to join" i]',
    'button[aria-label*="Join now" i]',
    'button:has-text("Ask to join")',
    'button:has-text("Join now")',
    'button:has-text("Switch here")',
)

#: Signals that the bot is in the waiting room rather than the meeting.
LOBBY_INDICATORS: Final[tuple[str, ...]] = (
    '[aria-label*="Please wait" i]',
    ".U0e0y",  # lobby copy container as of 2026-08
)

#: Text Meet renders while a host decides whether to admit the bot.
LOBBY_WAIT_TEXT: Final[str] = "Please wait until a meeting host brings you into the call"

# --------------------------------------------------------------------------
# In-meeting
# --------------------------------------------------------------------------

#: Any of these means the bot is inside the meeting room.
IN_MEETING_INDICATORS: Final[tuple[str, ...]] = (
    '[aria-label*="Leave call" i]',
    '[aria-label*="End call" i]',
    "[data-participant-id]",
    '[aria-label*="Chat with everyone" i]',
    '[aria-label*="Show everyone" i]',
)

#: Leave-call control.
LEAVE_BUTTONS: Final[tuple[str, ...]] = (
    'button[aria-label*="Leave call" i]',
    'button[aria-label*="End call" i]',
)

#: One element per visible participant. Counting these gives the headcount.
PARTICIPANT_TILE: Final[str] = "[data-participant-id]"

#: Toggle that opens the chat side panel.
CHAT_TOGGLE: Final[tuple[str, ...]] = (
    '[aria-label="Show chat"]',
    '[aria-label*="Chat with everyone" i]',
    'button:has-text("Chat")',
)

#: Toggle that switches captions on.
CAPTION_TOGGLE: Final[tuple[str, ...]] = (
    '[aria-label*="Turn on captions" i]',
    '[aria-label*="caption" i]',
    'button:has-text("Turn on captions")',
)

#: Keyboard shortcut for captions, used when the button cannot be found.
CAPTION_SHORTCUT: Final[str] = "c"

#: Live caption region. Its direct children are the caption blocks.
CAPTIONS_CONTAINER: Final[str] = '[aria-label="Captions"]'

#: Text Meet injects into the caption region that is not transcript.
CAPTION_NOISE_MARKERS: Final[tuple[str, ...]] = ("Jump to bottom",)

#: Microphone state marker. Present and false means the mic is live.
MIC_UNMUTED_MARKER: Final[str] = '[data-is-muted="false"]'

#: Keyboard shortcuts for the media toggles.
MIC_SHORTCUT: Final[str] = "Control+d"
CAMERA_SHORTCUT: Final[str] = "Control+e"

#: Camera-off control on the pre-join screen, where the in-meeting toggle is absent.
PREJOIN_CAMERA_OFF: Final[str] = '[aria-label*="Turn off camera" i]'

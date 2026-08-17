/**
 * Determine where the bot stands relative to the meeting room.
 *
 * Called with the selector groups owned by selectors.py so that DOM knowledge
 * stays in one place on the Python side.
 *
 * @param {{lobbySelectors: string[], lobbyText: string, inMeetingSelectors: string[]}} config
 * @returns {"LOBBY"|"IN_MEETING"|"UNKNOWN"}
 */
(config) => {
    const { lobbySelectors, lobbyText, inMeetingSelectors } = config;

    // Lobby is checked first: several in-meeting markers (participant tiles,
    // control bars) render behind the waiting-room overlay, so checking
    // "in meeting" first would produce a false positive.
    for (const selector of lobbySelectors) {
        try {
            if (document.querySelector(selector)) {
                return "LOBBY";
            }
        } catch (e) {
            // An invalid selector must not abort the whole probe.
        }
    }

    if (lobbyText) {
        const waiting = Array.from(document.querySelectorAll("div")).some(
            (el) => el.textContent && el.textContent.includes(lobbyText)
        );
        if (waiting) {
            return "LOBBY";
        }
    }

    for (const selector of inMeetingSelectors) {
        try {
            if (document.querySelector(selector)) {
                return "IN_MEETING";
            }
        } catch (e) {
            // Ignore and try the next candidate.
        }
    }

    return "UNKNOWN";
}

/**
 * Determine where the bot stands relative to the meeting room.
 *
 * @param {{
 *   lobbySelectors: string[],
 *   lobbyText: string,
 *   inMeetingSelectors: string[]
 * }} config
 *
 * @returns {"LOBBY"|"IN_MEETING"|"UNKNOWN"}
 */
(config) => {
    const { lobbySelectors, lobbyText, inMeetingSelectors } = config;

    /**
     * Check whether an element is actually visible.
     *
     * Google Meet can keep old lobby elements in the DOM after
     * the bot has been admitted, so querySelector() alone is not
     * reliable.
     */
    const isVisible = (el) => {
        if (!el) {
            return false;
        }

        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();

        return (
            style.display !== "none" &&
            style.visibility !== "hidden" &&
            rect.width > 0 &&
            rect.height > 0
        );
    };

    /**
     * Check whether any selector matches a visible element.
     */
    const hasVisibleSelector = (selectors) => {
        for (const selector of selectors) {
            try {
                const elements = document.querySelectorAll(selector);

                for (const el of elements) {
                    if (isVisible(el)) {
                        return true;
                    }
                }
            } catch (e) {
                // Ignore invalid selectors.
            }
        }

        return false;
    };

    // ============================================================
    // 1. CHECK IN-MEETING FIRST
    // ============================================================
    //
    // IMPORTANT:
    // Meet may leave lobby elements in the DOM after admission.
    // Therefore IN_MEETING must take priority over LOBBY.
    //

    if (hasVisibleSelector(inMeetingSelectors)) {
        return "IN_MEETING";
    }

    // Strong fallback: Leave/End call button
    try {
        const leaveButtons = document.querySelectorAll(
            '[aria-label*="Leave call" i], ' +
            '[aria-label*="End call" i]'
        );

        for (const el of leaveButtons) {
            if (isVisible(el)) {
                return "IN_MEETING";
            }
        }
    } catch (e) {
        // Ignore.
    }

    // Another useful in-meeting signal.
    try {
        const videos = document.querySelectorAll("video");

        for (const video of videos) {
            if (isVisible(video)) {
                return "IN_MEETING";
            }
        }
    } catch (e) {
        // Ignore.
    }

    // ============================================================
    // 2. CHECK LOBBY
    // ============================================================

    if (hasVisibleSelector(lobbySelectors)) {
        return "LOBBY";
    }

    // Check the actual waiting-room message.
    if (lobbyText) {
        try {
            const elements = document.querySelectorAll("body *");

            for (const el of elements) {
                if (!isVisible(el)) {
                    continue;
                }

                const text = (el.textContent || "").trim();

                if (text.includes(lobbyText)) {
                    return "LOBBY";
                }
            }
        } catch (e) {
            // Ignore.
        }
    }

    // ============================================================
    // 3. UNKNOWN
    // ============================================================

    return "UNKNOWN";
}
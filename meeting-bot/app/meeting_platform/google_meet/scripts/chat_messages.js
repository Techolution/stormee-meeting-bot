/**
 * Extract every chat message currently in the DOM.
 *
 * Returns the full visible history on each call; the caller tracks which
 * message ids it has already processed. Message ids come from Meet's own
 * `data-message-id`, which is stable for the life of the meeting.
 *
 * Sender attribution is structural rather than selector-based: Meet nests the
 * author's name in an ancestor block that is several levels above the message
 * node, and the exact depth varies between grouped and ungrouped messages. The
 * walk stops at the first ancestor that yields a name.
 *
 * @returns {{id: string, sender: string, text: string}[]}
 */
() => {
    const MAX_ANCESTOR_WALK = 8;
    const results = [];

    document.querySelectorAll("[data-message-id]").forEach((node) => {
        const id = node.getAttribute("data-message-id");

        // Meet uses data-message-id for other things too; real chat messages
        // are namespaced under "messages/".
        if (!id || !id.includes("messages/")) {
            return;
        }

        const textEl = node.querySelector('[jsname="dTKtvb"]') || node;
        const text = textEl ? textEl.innerText.trim() : "";
        if (!text) {
            return;
        }

        let sender = "Unknown";
        let parent = node.parentElement;

        for (let depth = 0; depth < MAX_ANCESTOR_WALK && parent; depth += 1) {
            const nameEl = parent.querySelector(".poVWob");
            if (nameEl && nameEl.innerText.trim()) {
                sender = nameEl.innerText.trim();
                break;
            }

            // Consecutive messages from one author omit the name block; the
            // avatar's alt text carries it instead.
            const avatar = parent.querySelector("img[alt]");
            if (avatar && avatar.getAttribute("alt")) {
                sender = avatar.getAttribute("alt").trim();
                break;
            }

            parent = parent.parentElement;
        }

        results.push({ id, sender, text });
    });

    return results;
}

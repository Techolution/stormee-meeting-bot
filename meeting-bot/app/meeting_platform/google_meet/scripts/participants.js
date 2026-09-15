/**
 * Install or remove Google Meet's active-speaker tracker.
 *
 * Scans participant tiles for Meet's visual speaking indicator — a glowing
 * blue border (rgb 138,180,248) or an animated waveform — and reports the
 * name of whoever is talking. Fires only on speaker *changes*.
 *
 * @param {{action?: "start"|"stop", callbackName: string}} config
 * @returns {boolean} Whether the requested operation changed tracker state.
 */
(config) => {
    const trackerKey = "__stormeeParticipantTracker";
    const existing = window[trackerKey];

    if (config.action === "stop") {
        if (!existing) return false;
        existing.observer.disconnect();
        window.clearTimeout(existing.debounceTimer);
        delete window[trackerKey];
        return true;
    }

    if (existing) return false;

    function getActiveSpeakerData() {
        const tiles = document.querySelectorAll("[data-participant-id]");

        for (const tile of tiles) {
            const parentContainer = tile.closest(".dkjMxf") || tile;
            const computedStyle = window.getComputedStyle(parentContainer);

            // Google's active speaker indicator: glowing blue border/box-shadow.
            const hasGlowingBorder =
                computedStyle.outlineColor.includes("138, 180, 248") ||
                computedStyle.borderColor.includes("138, 180, 248") ||
                computedStyle.boxShadow.includes("138, 180, 248");

            // Waveform animation, for standard participants and the self view.
            const hasWaveform =
                tile.querySelector(".IisKdb:not(.gjg47c), .KUNJSe, .HX2H7") !== null;

            if (!hasGlowingBorder && !hasWaveform) continue;

            const participantId = tile.getAttribute("data-participant-id");
            let name = "";

            // 1. "More options for [Name]" button — works for the bot and others.
            const moreBtn = tile.querySelector('button[aria-label*="More options for"]');
            if (moreBtn) {
                const label = moreBtn.getAttribute("aria-label") || "";
                name = label.replace(/^More options for\s+/i, "").trim();
            }

            // 2. Pin button — other participants.
            if (!name) {
                const pinBtn = tile.querySelector('button[aria-label*="Pin"]');
                if (pinBtn) {
                    const label = pinBtn.getAttribute("aria-label") || "";
                    name = label
                        .replace(/^Pin\s+/i, "")
                        .replace(/\s+to your main screen$/i, "")
                        .trim();
                }
            }

            // 3. Fall back to the name overlay text.
            if (!name) {
                const nameEl = tile.querySelector(".XEazBc span, .notranslate");
                if (nameEl) name = nameEl.textContent.trim();
            }

            return { id: participantId, name: name || null };
        }

        return null;
    }

    const state = {
        currentSpeakerId: null,
        debounceTimer: null,
        observer: null,
    };

    const publishIfChanged = () => {
        const active = getActiveSpeakerData();
        const activeId = active ? active.id : null;
        if (activeId === state.currentSpeakerId) return;

        state.currentSpeakerId = activeId;
        if (active) {
            console.log("Active Speaker:", active.name, `(${active.id})`);
        } else {
            console.log("Silence");
        }

        const callback = window[config.callbackName];
        if (typeof callback === "function") {
            void callback({
                id: activeId,
                name: active ? active.name : null,
                observedAt: new Date().toISOString(),
            });
        }
    };

    const observer = new MutationObserver(() => {
        window.clearTimeout(state.debounceTimer);
        state.debounceTimer = window.setTimeout(publishIfChanged, 150);
    });
    state.observer = observer;
    observer.observe(document.querySelector("main") || document.body, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ["class"],
    });

    window[trackerKey] = state;
    publishIfChanged();
    return true;
}
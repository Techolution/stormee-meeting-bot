/**
 * Dismiss the "Sign in with your Google account" interstitial.
 *
 * Tries the acknowledge button first. If the button is missing or the modal
 * survives the click, the container and its dialog wrapper are removed
 * outright — the modal is purely advisory and blocks the pre-join controls
 * underneath it.
 *
 * @param {{buttonSelectors: string[], containerSelector: string}} config
 * @returns {boolean} whether anything was dismissed
 */
(config) => {
    const { buttonSelectors, containerSelector } = config;
    let dismissed = false;

    for (const selector of buttonSelectors) {
        let button = null;
        try {
            button = document.querySelector(selector);
        } catch (e) {
            continue;
        }
        if (button) {
            button.click();
            dismissed = true;
            break;
        }
    }

    const popup = containerSelector ? document.querySelector(containerSelector) : null;
    if (popup) {
        const inner = popup.querySelector("button");
        if (inner) {
            inner.click();
        }
        const wrapper = popup.closest('[role="dialog"]') || popup.parentElement;
        if (wrapper) {
            wrapper.remove();
        }
        dismissed = true;
    }

    return dismissed;
}

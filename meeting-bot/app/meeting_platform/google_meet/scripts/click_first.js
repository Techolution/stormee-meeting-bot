/**
 * Click the first element matching any of the given selectors.
 *
 * A direct DOM click, used where Playwright's own click is unreliable: Meet
 * overlays transparent elements above its controls and disables the join button
 * until its React state settles, both of which make a synthetic click fail
 * while a DOM click succeeds.
 *
 * `enableFirst` clears the `disabled` attribute before clicking. Meet leaves the
 * join button disabled after the name field is filled until an internal state
 * update lands, and waiting for that is slower and flakier than clearing it.
 *
 * @param {{selectors: string[], enableFirst?: boolean}} config
 * @returns {boolean} whether an element was found and clicked
 */
(config) => {
    const { selectors, enableFirst = false } = config;

    for (const selector of selectors) {
        let element = null;
        try {
            element = document.querySelector(selector);
        } catch (e) {
            continue;
        }

        if (!element) {
            continue;
        }

        if (enableFirst) {
            element.disabled = false;
            element.removeAttribute("disabled");
        }

        element.click();
        return true;
    }

    return false;
}

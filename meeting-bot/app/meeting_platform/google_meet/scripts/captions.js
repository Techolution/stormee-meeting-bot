/**
 * Read the live caption region.
 *
 * Meet renders one block per active speaker and rewrites those blocks in place
 * as speech continues, so this returns a snapshot of what is on screen right
 * now — not an append-only log. Consecutive calls overlap heavily and the
 * caller is responsible for turning the sequence of snapshots into a
 * transcript.
 *
 * Each block's first line is the speaker; the remainder is the utterance.
 *
 * @param {{containerSelector: string, noiseMarkers: string[]}} config
 * @returns {{speaker: string, text: string}[]}
 */
(config) => {
    const { containerSelector, noiseMarkers } = config;

    const container = document.querySelector(containerSelector);
    if (!container) {
        return [];
    }

    const blocks = [];

    for (const row of Array.from(container.children)) {
        const raw = row.innerText;
        if (!raw) {
            continue;
        }

        // Meet injects controls such as "Jump to bottom" into the same region.
        if (noiseMarkers.some((marker) => raw.includes(marker))) {
            continue;
        }

        const lines = raw
            .split("\n")
            .map((line) => line.trim())
            .filter((line) => line.length > 0);

        // A block without at least a speaker and one line of speech is still
        // being assembled.
        if (lines.length < 2) {
            continue;
        }

        blocks.push({
            speaker: lines[0],
            text: lines.slice(1).join(" "),
        });
    }

    return blocks;
}

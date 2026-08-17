/**
 * Play audio into the meeting through the virtual microphone.
 *
 * `window.__meetingAudio` is installed by audio_pipeline.js as an init script.
 * Its absence means the pipeline never ran — usually because the page was
 * navigated before the script was registered — so it is reported rather than
 * silently ignored.
 *
 * @param {{audioUrl: string, volume: number}} config
 * @returns {Promise<void>}
 */
async (config) => {
    const { audioUrl, volume } = config;

    if (!window.__meetingAudio) {
        throw new Error("meeting audio pipeline is not installed on this page");
    }

    window.__meetingAudio.setMicVolume(volume);
    await window.__meetingAudio.playIntoMic(audioUrl);
}

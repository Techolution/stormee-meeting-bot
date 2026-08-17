INITIALIZE_SEPRATE_AUDIO_CHANNELS_FOR_REMOTE_AND_INPUT = """
(() => {
    const originalGetUserMedia =
        navigator.mediaDevices.getUserMedia.bind(
            navigator.mediaDevices
        );

    let micAudioElement = null;
    let micAudioContext = null;
    let micSourceNode = null;
    let micGainNode = null;
    let micDestinationNode = null;
    let micTrack = null;

    let micInitialized = false;
    let micInitializationPromise = null;

    window.remoteAudioStreams =
        window.remoteAudioStreams || [];

    async function initializeVirtualMic() {
        if (micInitialized && micTrack) {
            return;
        }

        if (micInitializationPromise) {
            await micInitializationPromise;
            return;
        }

        micInitializationPromise = (async () => {

            micAudioElement =
                document.createElement("audio");

            micAudioElement.id =
                "__meeting_virtual_mic_audio";

            micAudioElement.crossOrigin = "anonymous";
            micAudioElement.preload = "auto";
            micAudioElement.style.display = "none";

            document.documentElement.appendChild(
                micAudioElement
            );

            micAudioContext =
                new (
                    window.AudioContext ||
                    window.webkitAudioContext
                )();

            micSourceNode =
                micAudioContext.createMediaElementSource(
                    micAudioElement
                );

            micGainNode =
                micAudioContext.createGain();

            micDestinationNode =
                micAudioContext.createMediaStreamDestination();

            micGainNode.gain.value = 1.0;

            micSourceNode.connect(micGainNode);

            // This is what Meet receives.
            micGainNode.connect(
                micDestinationNode
            );

            const tracks =
                micDestinationNode.stream
                    .getAudioTracks();

            if (!tracks.length) {
                throw new Error(
                    "Failed to create virtual microphone track"
                );
            }

            micTrack = tracks[0];

            micInitialized = true;

            console.log(
                "✅ Virtual microphone initialized"
            );
        })();

        try {
            await micInitializationPromise;
        } finally {
            micInitializationPromise = null;
        }
    }


    async function playIntoMic(audioUrl) {

        await initializeVirtualMic();

        if (
            micAudioContext.state ===
            "suspended"
        ) {
            await micAudioContext.resume();
        }

        micAudioElement.pause();

        micAudioElement.currentTime = 0;

        micAudioElement.src = audioUrl;

        micAudioElement.load();

        await new Promise((resolve, reject) => {

            const onReady = () => {
                cleanup();
                resolve();
            };

            const onError = (event) => {
                cleanup();

                reject(
                    new Error(
                        "Failed to load audio: " +
                        event
                    )
                );
            };

            const cleanup = () => {
                micAudioElement.removeEventListener(
                    "canplay",
                    onReady
                );

                micAudioElement.removeEventListener(
                    "error",
                    onError
                );
            };

            micAudioElement.addEventListener(
                "canplay",
                onReady,
                { once: true }
            );

            micAudioElement.addEventListener(
                "error",
                onError,
                { once: true }
            );
        });

        await micAudioElement.play();

        console.log(
            "▶️ Bot audio playing into virtual mic"
        );
    }


    function setMicVolume(volume) {

        if (!micGainNode) {
            return;
        }

        micGainNode.gain.value =
            Math.max(
                0,
                Math.min(1, volume)
            );
    }


    function getVirtualMicStream() {

        if (!micDestinationNode) {
            return null;
        }

        return micDestinationNode.stream;
    }


    // ============================================================
    // OVERRIDE getUserMedia
    // ============================================================

    navigator.mediaDevices.getUserMedia =
        async function(constraints) {

            console.log(
                "🎙️ getUserMedia:",
                constraints
            );

            if (
                constraints &&
                constraints.audio
            ) {

                await initializeVirtualMic();

                const stream =
                    new MediaStream();

                stream.addTrack(
                    micTrack.clone()
                );

                return stream;
            }

            return originalGetUserMedia(
                constraints
            );
        };

    const OriginalRTCPeerConnection =
        window.RTCPeerConnection;

        function WrappedRTCPeerConnection(...args) {

            const pc =
                new OriginalRTCPeerConnection(...args);

        pc.addEventListener(
            "track",
            (event) => {

                if (
                    event.track.kind !== "audio"
                ) {
                    return;
                }

                const stream =
                    event.streams &&
                    event.streams.length
                        ? event.streams[0]
                        : null;

                if (!stream) {
                    return;
                }

                window.remoteAudioStreams = window.remoteAudioStreams || [];

                if (
                    !window.remoteAudioStreams
                        .includes(stream)
                ) {

                    window.remoteAudioStreams.push(
                        stream
                    );
                }

                console.log(
                    "📥 Remote audio stream captured"
                );

                window.dispatchEvent(
                    new CustomEvent(
                        "remoteStreamAdded",
                        {
                            detail: stream
                        }
                    )
                );
            }
        );

        return pc;
    }

    WrappedRTCPeerConnection.prototype =
        OriginalRTCPeerConnection.prototype;

    Object.setPrototypeOf(
        WrappedRTCPeerConnection,
        OriginalRTCPeerConnection
    );

    window.RTCPeerConnection = WrappedRTCPeerConnection;

    // ============================================================
    // PUBLIC API
    // ============================================================

    window.__meetingAudio = {

        initializeVirtualMic,

        playIntoMic,

        setMicVolume,

        getVirtualMicStream,

        getMicState: () => ({
            initialized: micInitialized,

            audioContextState:
                micAudioContext
                    ? micAudioContext.state
                    : null,

            playing:
                micAudioElement
                    ? !micAudioElement.paused
                    : false,

            trackEnabled:
                micTrack
                    ? micTrack.enabled
                    : false,

            trackReadyState:
                micTrack
                    ? micTrack.readyState
                    : null
        })
    };

})();
"""

UNSET_WEB_DRIVER = """
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined
    });
"""

RECORDING_STARTER = """
    async (meetingId) => {

        try {

            // =====================================================
            // INITIALIZE VIRTUAL MIC
            // =====================================================

            if (
                window.__meetingAudio &&
                window.__meetingAudio.initializeVirtualMic
            ) {
                await window.__meetingAudio
                    .initializeVirtualMic();
            }


            // =====================================================
            // CLEANUP OLD RECORDER
            // =====================================================

            if (window.mediaRecorder) {

                try {

                    if (
                        window.mediaRecorder.state !==
                        "inactive"
                    ) {
                        window.mediaRecorder.stop();
                    }

                } catch (e) {
                    console.warn(
                        "Failed stopping old recorder:",
                        e
                    );
                }

                window.mediaRecorder = null;
            }


            // =====================================================
            // REMOVE OLD LISTENER
            // =====================================================

            if (window.remoteStreamListener) {

                window.removeEventListener(
                    "remoteStreamAdded",
                    window.remoteStreamListener
                );

                window.remoteStreamListener = null;
            }


            // =====================================================
            // CREATE RECORDING AUDIO CONTEXT
            // =====================================================

            const audioCtx = new (
                    window.AudioContext ||
                    window.webkitAudioContext
                )();

            window.recordingAudioContext = audioCtx;


            if (audioCtx.state === "suspended") {
                await audioCtx.resume();
            }


            // =====================================================
            // FINAL RECORDING DESTINATION
            // =====================================================

            const destination =
                audioCtx.createMediaStreamDestination();

            window.recordingDestination =
                destination;


            // =====================================================
            // TRACK WHICH STREAMS WE CONNECTED
            // =====================================================

            const connectedStreams = new WeakSet();


            function connectToRecording(
                stream,
                label
            ) {

                if (!stream) {
                    return;
                }

                if (
                    connectedStreams.has(stream)
                ) {
                    return;
                }

                const tracks =
                    stream.getAudioTracks();

                if (!tracks.length) {
                    console.warn(
                        `⚠️ ${label} has no audio`
                    );

                    return;
                }

                    const source =
                        audioCtx.createMediaStreamSource(
                            stream
                        );


                    source.connect(destination);


                    connectedStreams.add(stream);


                console.log(
                    `🔊 Recording: ${label}`
                );
            }


            // =====================================================
            // BOT AUDIO
            // =====================================================

            const virtualMicStream =
                window.__meetingAudio
                    .getVirtualMicStream();


            if (!virtualMicStream) {

                throw new Error(
                    "Virtual microphone stream unavailable"
                );
            }


            connectToRecording(
                virtualMicStream,
                "BOT AUDIO"
            );


            // =====================================================
            // EXISTING REMOTE AUDIO
            // =====================================================

            if (
                window.remoteAudioStreams
            ) {

                window.remoteAudioStreams
                    .forEach(
                        (stream, index) => {

                            connectToRecording(
                                stream,
                                `REMOTE ${index}`
                            );
                        }
                    );
            }


            // =====================================================
            // FUTURE REMOTE AUDIO
            // =====================================================

            window.remoteStreamListener =
                (event) => {

                    const stream =
                        event.detail;

                    connectToRecording(
                        stream,
                        "REMOTE NEW"
                    );
                };


            window.addEventListener(
                "remoteStreamAdded",
                window.remoteStreamListener
            );


            // =====================================================
            // CREATE RECORDER
            // =====================================================

            const recordingStream =
                destination.stream;


            const recorder =
                new MediaRecorder(
                    recordingStream,
                    {
                        mimeType:
                            "audio/webm;codecs=opus"
                    }
                );


            window.mediaRecorder =
                recorder;


            // =====================================================
            // CHUNKS
            // =====================================================

            window.chunkCounter = 0;

            window.pendingAudioChunkPromises = [];


            recorder.ondataavailable =
                async (event) => {

                    if (
                        event.data.size === 0
                    ) {
                        return;
                    }

                    const chunkId =
                        `${meetingId}-${window.chunkCounter++}`;

                    const timestamp =
                        new Date().toISOString();


                    const buffer =
                        await event.data
                            .arrayBuffer();


                    const audioBlob =
                        Array.from(
                            new Uint8Array(buffer)
                        );


                    const promise =
                        window
                            .sendAudioChunkToPython({
                                meetingId,
                                chunkId,
                                timestamp,
                                audioBlob
                            });


                    window
                        .pendingAudioChunkPromises
                        .push(promise);


                    try {
                        await promise;
                    } finally {

                        window
                            .pendingAudioChunkPromises =
                            window
                                .pendingAudioChunkPromises
                                .filter(
                                    p =>
                                        p !== promise
                                );
                    }
                };


            recorder.onerror =
                (event) => {

                    console.error(
                        "❌ Recorder error:",
                        event.error
                    );
                };


            recorder.onstart =
                () => {

                    console.log(
                        "▶️ Recording started"
                    );
                };


            recorder.onstop =
                () => {

                    console.log(
                        "🛑 Recording stopped"
                    );
                };


            // =====================================================
            // START
            // =====================================================

            recorder.start(5000);


            console.log(
                "✅ Recording started:",
                meetingId
            );

        } catch (error) {

            console.error(
                "❌ Recording initialization failed:",
                error
            );

            throw error;
        }
    }
    """

RECORDING_STOPPER = """
    async () => {
        const recorder = window.mediaRecorder;

        if (!recorder) {
            console.log("No MediaRecorder exists");
            return;
        }

        if (recorder.state === "inactive") {
            console.log("MediaRecorder already inactive");
            return;
        }

        await new Promise((resolve) => {
            const originalOnStop = recorder.onstop;

            recorder.onstop = (event) => {
                console.log(
                    "🛑 MediaRecorder stopped - final chunk emitted"
                );

                if (originalOnStop) {
                    try {
                        originalOnStop(event);
                    } catch (e) {
                        console.warn(
                            "Original onstop handler failed:",
                            e
                        );
                    }
                }

                resolve();
            };

            try {
                recorder.requestData();
            } catch (e) {
                console.warn(
                    "requestData before stop failed:",
                    e
                );
            }

            recorder.stop();
        });

        if (
            window.pendingAudioChunkPromises &&
            window.pendingAudioChunkPromises.length > 0
        ) {
            console.log(
                `⏳ Waiting for ${window.pendingAudioChunkPromises.length} ` +
                `pending audio chunk send(s)`
            );
            await Promise.allSettled(window.pendingAudioChunkPromises);
        }
    }
"""
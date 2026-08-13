INITIALIZE_SEPRATE_AUDIO_CHANNELS_FOR_REMOTE_AND_INPUT = """
(() => {
    console.log("🎙️ Installing meeting audio pipeline...");

    // ============================================================
    // VIRTUAL MICROPHONE
    // ============================================================

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


    async function initializeVirtualMicrophone() {
        if (micInitialized && micTrack) {
            return;
        }

        if (micInitializationPromise) {
            return micInitializationPromise;
        }

        micInitializationPromise = (async () => {

            console.log("🎙️ Initializing virtual microphone...");

            micAudioElement = document.createElement("audio");

            micAudioElement.id =
                "__python_virtual_microphone_audio";

            micAudioElement.crossOrigin = "anonymous";
            micAudioElement.preload = "auto";
            micAudioElement.style.display = "none";

            document.documentElement.appendChild(
                micAudioElement
            );


            micAudioContext = new (
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


            // Audio:
            //
            // HTMLAudioElement
            //        ↓
            // MediaElementSource
            //        ↓
            // GainNode
            //        ↓
            // MediaStreamDestination
            //        ↓
            // MediaStreamTrack
            //        ↓
            // Google Meet microphone
            //

            micSourceNode.connect(
                micGainNode
            );

            micGainNode.connect(
                micDestinationNode
            );


            const tracks =
                micDestinationNode.stream.getAudioTracks();


            if (!tracks.length) {
                throw new Error(
                    "Failed to create virtual microphone track"
                );
            }


            micTrack = tracks[0];

            micTrack.enabled = true;

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


    async function playIntoMicrophone(dataUrl) {

        await initializeVirtualMicrophone();


        if (micAudioContext.state === "suspended") {
            await micAudioContext.resume();
        }


        console.log(
            "🎙️ Loading audio into virtual microphone..."
        );


        micAudioElement.pause();

        micAudioElement.currentTime = 0;

        micAudioElement.src = dataUrl;

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
                        "Failed to load microphone audio"
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
            "🎙️ Python audio is now being sent to virtual microphone"
        );
    }


    function stopMicrophoneAudio() {

        if (!micAudioElement) {
            return;
        }

        micAudioElement.pause();

        micAudioElement.currentTime = 0;

        console.log(
            "⏹️ Virtual microphone audio stopped"
        );
    }


    function pauseMicrophoneAudio() {

        if (micAudioElement) {
            micAudioElement.pause();
        }
    }


    async function resumeMicrophoneAudio() {

        if (!micAudioElement) {
            return;
        }


        if (
            micAudioContext &&
            micAudioContext.state === "suspended"
        ) {
            await micAudioContext.resume();
        }


        await micAudioElement.play();
    }


    function setMicrophoneVolume(volume) {

        if (!micGainNode) {
            return;
        }


        volume = Math.max(
            0,
            Math.min(1, Number(volume))
        );


        micGainNode.gain.value = volume;


        console.log(
            "🎙️ Virtual microphone volume:",
            volume
        );
    }


    // ============================================================
    // OVERRIDE getUserMedia
    // ============================================================

    navigator.mediaDevices.getUserMedia =
        async function(constraints) {

            console.log(
                "🎙️ getUserMedia requested:",
                constraints
            );


            if (
                constraints &&
                constraints.audio
            ) {

                await initializeVirtualMicrophone();


                const track =
                    micTrack.clone();


                track.enabled = true;


                const stream =
                    new MediaStream();


                stream.addTrack(track);


                console.log(
                    "🎙️ Returning virtual microphone stream"
                );


                return stream;
            }


            // Keep normal camera behavior.
            return originalGetUserMedia(
                constraints
            );
        };


    // ============================================================
    // REMOTE WEBRTC AUDIO CAPTURE
    // ============================================================

    const OriginalRTCPeerConnection =
        window.RTCPeerConnection;


    window.remoteAudioStreams =
        window.remoteAudioStreams || [];


    window.remoteAudioTracks =
        window.remoteAudioTracks || [];


    window.RTCPeerConnection =
        function(...args) {

            console.log(
                "🌐 RTCPeerConnection created"
            );


            const pc =
                new OriginalRTCPeerConnection(...args);


            pc.addEventListener(
                "track",
                (event) => {

                    console.log(
                        "📥 WebRTC track received:",
                        event.track.kind
                    );


                    if (
                        event.track.kind !== "audio"
                    ) {
                        return;
                    }


                    const remoteStream =
                        event.streams &&
                        event.streams.length > 0
                            ? event.streams[0]
                            : null;


                    if (!remoteStream) {

                        console.warn(
                            "⚠️ Remote audio track has no stream"
                        );

                        return;
                    }


                    // Avoid storing the exact same stream repeatedly.
                    if (
                        !window.remoteAudioStreams.includes(
                            remoteStream
                        )
                    ) {

                        window.remoteAudioStreams.push(
                            remoteStream
                        );
                    }


                    if (
                        !window.remoteAudioTracks.includes(
                            event.track
                        )
                    ) {

                        window.remoteAudioTracks.push(
                            event.track
                        );
                    }


                    console.log(
                        "📥 Remote audio stream captured"
                    );


                    window.dispatchEvent(
                        new CustomEvent(
                            "remoteStreamAdded",
                            {
                                detail: {
                                    stream: remoteStream,
                                    track: event.track
                                }
                            }
                        )
                    );
                }
            );


            return pc;
        };


    // ============================================================
    // PUBLIC API
    // ============================================================

    window.__meetingAudio = {
        
        // Virtual microphone
        initializeVirtualMic: async () => {
            await initializeVirtualMicrophone();
            return true;
        },

        playIntoMic: async (dataUrl) => {
            await playIntoMicrophone(dataUrl);
        },

        stopMic: () => {
            stopMicrophoneAudio();
        },

        pauseMic: () => {
            pauseMicrophoneAudio();
        },

        resumeMic: async () => {
            await resumeMicrophoneAudio();
        },

        setMicVolume: (volume) => {
            setMicrophoneVolume(volume);
        },

        getVirtualMicStream: () => {
            if (!micDestinationNode) {
                return null;
            }

            return micDestinationNode.stream;
        },


        // Remote WebRTC
        getRemoteStreams: () => {
            return window.remoteAudioStreams;
        },

        getRemoteTracks: () => {
            return window.remoteAudioTracks;
        },

        getRemoteStreamCount: () => {
            return window.remoteAudioStreams.length;
        },


        // Debugging
        getMicState: () => {

            return {
                initialized: micInitialized,

                audioContextState:
                    micAudioContext
                        ? micAudioContext.state
                        : null,

                playing:
                    micAudioElement
                        ? !micAudioElement.paused
                        : false,

                currentTime:
                    micAudioElement
                        ? micAudioElement.currentTime
                        : 0,

                duration:
                    micAudioElement
                        ? micAudioElement.duration
                        : 0,

                trackEnabled:
                    micTrack
                        ? micTrack.enabled
                        : false,

                trackReadyState:
                    micTrack
                        ? micTrack.readyState
                        : null
            };
        }
    };


    console.log(
        "✅ Meeting audio pipeline installed"
    );

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
            if (
                window.__meetingAudio &&
                window.__meetingAudio.initializeVirtualMic
            ) {
                await window.__meetingAudio.initializeVirtualMic();
            }
            // ======================================================
            // CLEAN UP PREVIOUS RECORDER
            // ======================================================

            if (window.mediaRecorder) {
                try {
                    if (
                        window.mediaRecorder.state !== "inactive"
                    ) {
                        window.mediaRecorder.stop();
                    }
                } catch (e) {
                    console.warn(
                        "Failed to stop previous recorder:",
                        e
                    );
                }

                window.mediaRecorder = null;
            }


            // ======================================================
            // REMOVE PREVIOUS REMOTE STREAM LISTENER
            // ======================================================

            if (window.remoteStreamListener) {
                try {
                    window.removeEventListener(
                        "remoteStreamAdded",
                        window.remoteStreamListener
                    );
                } catch (e) {
                    console.warn(
                        "Failed to remove old remote listener:",
                        e
                    );
                }

                window.remoteStreamListener = null;
            }


            // ======================================================
            // CLOSE PREVIOUS RECORDING AUDIO CONTEXT
            // ======================================================

            if (window.recordingAudioContext) {
                try {
                    await window.recordingAudioContext.close();
                } catch (e) {
                    console.warn(
                        "Failed to close previous AudioContext:",
                        e
                    );
                }

                window.recordingAudioContext = null;
            }


            // ======================================================
            // CREATE RECORDING AUDIO CONTEXT
            // ======================================================

            const audioCtx = new (
                    window.AudioContext ||
                    window.webkitAudioContext
                )();

            window.recordingAudioContext = audioCtx;


            if (audioCtx.state === "suspended") {
                await audioCtx.resume();
            }


            // This is the final mixed audio stream.
            const destination =
                audioCtx.createMediaStreamDestination();

            window.recordingDestination =
                destination;


            // ======================================================
            // PREVENT DUPLICATE CONNECTIONS
            // ======================================================

            const connectedStreams = new WeakSet();


            function connectStreamToRecording(
                stream,
                label
            ) {
                if (!stream) {
                    return;
                }

                try {

                    if (connectedStreams.has(stream)) {
                        console.log(
                            `⚠️ ${label} already connected`
                        );

                        return;
                    }


                    const audioTracks =
                        stream.getAudioTracks();


                    if (!audioTracks.length) {
                        console.warn(
                            `⚠️ ${label} has no audio tracks`
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
                        `🔊 Connected ${label} to recording`
                    );

                } catch (e) {

                    console.error(
                        `❌ Failed to connect ${label}:`,
                        e
                    );
                }
            }


            // ======================================================
            // CONNECT BOT / VIRTUAL MICROPHONE AUDIO
            // ======================================================

            try {

                if (
                    window.__meetingAudio &&
                    window.__meetingAudio.getVirtualMicStream
                ) {

                    const virtualMicStream =
                        window.__meetingAudio
                            .getVirtualMicStream();


                    if (virtualMicStream) {

                        connectStreamToRecording(
                            virtualMicStream,
                            "bot / virtual microphone audio"
                        );

                    } else {

                        console.warn(
                            "⚠️ Virtual microphone stream " +
                            "not initialized yet"
                        );
                    }

                } else {

                    console.warn(
                        "⚠️ __meetingAudio.getVirtualMicStream " +
                        "is not available"
                    );
                }

            } catch (e) {

                console.error(
                    "❌ Failed to connect virtual mic:",
                    e
                );
            }


            // ======================================================
            // CONNECT EXISTING REMOTE WEBRTC STREAMS
            // ======================================================

            if (
                window.remoteAudioStreams &&
                window.remoteAudioStreams.length > 0
            ) {

                window.remoteAudioStreams.forEach(
                    (stream, index) => {

                        connectStreamToRecording(
                            stream,
                            `remote stream ${index}`
                        );

                    }
                );

            } else {

                console.warn(
                    "⚠️ No remote audio streams yet"
                );
            }


            // ======================================================
            // CONNECT FUTURE REMOTE STREAMS
            // ======================================================

            window.remoteStreamListener =
                (event) => {

                    try {

                        const detail =
                            event.detail;


                        // Support both:
                        //
                        // CustomEvent({ detail: stream })
                        //
                        // and
                        //
                        // CustomEvent({
                        //     detail: {
                        //         stream,
                        //         track
                        //     }
                        // })
                        //

                        const stream =
                            detail &&
                            detail.stream
                                ? detail.stream
                                : detail;


                        connectStreamToRecording(
                            stream,
                            "new remote stream"
                        );

                    } catch (e) {

                        console.error(
                            "❌ Failed to connect new " +
                            "remote stream:",
                            e
                        );
                    }
                };


            window.addEventListener(
                "remoteStreamAdded",
                window.remoteStreamListener
            );


            // ======================================================
            // CREATE MEDIA RECORDER
            // ======================================================

            const mixedStream =
                destination.stream;


            console.log(
                "🎙️ Recording audio tracks:",
                mixedStream.getAudioTracks().length
            );


            const mediaRecorder =
                new MediaRecorder(
                    mixedStream,
                    {
                        mimeType:
                            "audio/webm; codecs=opus"
                    }
                );


            window.mediaRecorder =
                mediaRecorder;


            // ======================================================
            // CHUNK STATE
            // ======================================================

            window.chunkCounter = 0;

            window.pendingAudioChunkPromises = [];


            // ======================================================
            // AUDIO CHUNKS
            // ======================================================

            mediaRecorder.ondataavailable =
                async (event) => {

                    if (event.data.size <= 0) {
                        return;
                    }


                    const chunkId =
                        `${meetingId}-${window.chunkCounter++}`;


                    const timestamp =
                        new Date().toISOString();


                    const sendPromise =
                        (async () => {

                            try {

                                const arrayBuffer =
                                    await event.data.arrayBuffer();


                                const audioBlob =
                                    Array.from(
                                        new Uint8Array(
                                            arrayBuffer
                                        )
                                    );


                                console.log(
                                    `📤 Chunk ready: ` +
                                    `${chunkId}, ` +
                                    `size: ` +
                                    `${event.data.size} bytes`
                                );


                                if (
                                    window.sendAudioChunkToPython
                                ) {

                                    try {

                                        await window
                                            .sendAudioChunkToPython({
                                                meetingId:
                                                    meetingId,

                                                chunkId:
                                                    chunkId,

                                                timestamp:
                                                    timestamp,

                                                audioBlob:
                                                    audioBlob
                                            });

                                    } catch (error) {

                                        console.error(
                                            "❌ Error sending " +
                                            "chunk:",
                                            error
                                        );
                                    }

                                } else {

                                    console.error(
                                        "❌ sendAudioChunkToPython " +
                                        "not available"
                                    );
                                }

                            } catch (error) {

                                console.error(
                                    "❌ Failed to process " +
                                    "audio chunk:",
                                    error
                                );
                            }

                        })();


                    window.pendingAudioChunkPromises.push(
                        sendPromise
                    );


                    try {
                        await sendPromise;
                    } finally {

                        window
                            .pendingAudioChunkPromises =
                            window
                                .pendingAudioChunkPromises
                                .filter(
                                    (promise) =>
                                        promise !==
                                        sendPromise
                                );
                    }
                };


            // ======================================================
            // RECORDER EVENTS
            // ======================================================

            mediaRecorder.onerror =
                (event) => {

                    console.error(
                        "❌ MediaRecorder error:",
                        event.error
                    );
                };


            mediaRecorder.onstart =
                () => {

                    console.log(
                        "▶️ MediaRecorder started"
                    );
                };


            mediaRecorder.onstop =
                () => {

                    console.log(
                        "🛑 MediaRecorder stopped"
                    );
                };


            // ======================================================
            // START
            // ======================================================

            mediaRecorder.start(5000);


            console.log(
                "✅ Recording started for:",
                meetingId
            );


            console.log(
                "🎙️ Recording contains:",
                "remote WebRTC audio + " +
                "bot virtual microphone audio"
            );


        } catch (error) {

            console.error(
                "❌ Error starting recording:",
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
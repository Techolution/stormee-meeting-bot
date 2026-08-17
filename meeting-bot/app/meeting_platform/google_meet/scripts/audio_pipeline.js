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

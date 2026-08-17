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
    

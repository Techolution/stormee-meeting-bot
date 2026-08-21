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
            // FEATURE FLAG: OPUS TRANSPORT
            // ======================================================
            
            // NEW PATH: Stream Opus encoding via AudioWorklet
            // OLD PATH: MediaRecorder-based WebM chunks
            const useOpusTransport = window.useOpusTransport || false;
            
            console.log(
                `🎙️ Recording transport: ${useOpusTransport ? "Opus Streaming" : "MediaRecorder"}`
            );

            // ======================================================
            // AUDIO WORKLET SETUP (NEW PATH)
            // ======================================================
            
            if (useOpusTransport) {
                try {
                    // Load the AudioWorklet processor
                    // The processor URL should point to the compiled/bundled opus_worklet_processor.js
                    const processorUrl = "/static/scripts/opus_worklet_processor.js";
                    
                    await audioCtx.audioWorklet.addModule(processorUrl);
                    
                    console.log(
                        "🎙️ AudioWorklet processor loaded"
                    );
                    
                    // Create the AudioWorklet node
                    const workletNode = new AudioWorkletNode(
                        audioCtx,
                        "opus-capture",
                        {
                            processorOptions: {
                                sampleRate: audioCtx.sampleRate,
                                channels: 1, // Mono for Opus encoding
                                sampleFormat: "float32"
                            }
                        }
                    );
                    
                    // Connect the mixed audio destination to the worklet
                    destination.connect(workletNode);
                    
                    // Store reference for cleanup and message handling
                    window.recordingAudioWorklet = workletNode;
                    
                    // Create PCM frame collector for 5-second chunking
                    const frameCollector = new PcmFrameCollector({
                        sampleRate: audioCtx.sampleRate,
                        channels: 1,  // Mono for Opus
                        onFrameReady: (frame) => {
                            // Frame ready for Opus encoding
                            // Will be connected to Opus encoder in future ACT
                            if (window.handleOpusFrame) {
                                window.handleOpusFrame(frame);
                            }
                        },
                        onMetricsUpdate: (metrics) => {
                            // Store metrics for monitoring
                            if (window.recordingFrameMetrics) {
                                Object.assign(window.recordingFrameMetrics, metrics);
                            }
                        }
                    });
                    
                    window.recordingFrameCollector = frameCollector;
                    window.recordingFrameMetrics = {};
                    
                    // Create Opus encoder for 5-second frames
                    const opusEncoder = new OpusEncoder({
                        sampleRate: audioCtx.sampleRate,
                        channels: 1,  // Mono
                        bitrate: 96,  // kbps for speech
                        onEncodedPacket: (packet) => {
                            // Handle encoded Opus packet
                            // Will be connected to upload queue in future ACT
                            if (window.handleEncodedPacket) {
                                window.handleEncodedPacket(packet);
                            }
                        },
                        onMetricsUpdate: (metrics) => {
                            if (window.recordingEncoderMetrics) {
                                Object.assign(window.recordingEncoderMetrics, metrics);
                            }
                        }
                    });
                    
                    window.recordingOpusEncoder = opusEncoder;
                    window.recordingEncoderMetrics = {};
                    
                    // Create upload queue manager for chunk sequencing and upload
                    const uploadQueue = new UploadQueueManager({
                        meetingId: meetingId,
                        onChunkReady: (chunk) => {
                            // Chunk is ready for upload (integrated with sendAudioChunkToPython)
                        },
                        maxQueueSize: 10 * 1024 * 1024,  // 10MB queue limit
                        onMetricsUpdate: (metrics) => {
                            if (window.recordingUploadMetrics) {
                                Object.assign(window.recordingUploadMetrics, metrics);
                            }
                        }
                    });
                    
                    window.recordingUploadQueue = uploadQueue;
                    window.recordingUploadMetrics = {};
                    
                    // Create session manager for 5-minute session boundaries
                    const sessionManager = new UploadSessionManager({
                        meetingId: meetingId,
                        uploadQueue: uploadQueue,
                        onSessionFinalized: (sessionData) => {
                            // Emit session finalization for container construction
                            console.log(
                                `[recorder_start] Session finalized: ${sessionData.uploadSessionId}, ` +
                                `chunks: ${sessionData.chunkCount}, ` +
                                `size: ${(sessionData.byteCount / (1024 * 1024)).toFixed(2)}MB`
                            );
                        },
                        onMetricsUpdate: (metrics) => {
                            if (window.recordingSessionMetrics) {
                                Object.assign(window.recordingSessionMetrics, metrics);
                            }
                        },
                        sessionDurationMs: 5 * 60 * 1000  // 5 minutes
                    });
                    
                    window.recordingSessionManager = sessionManager;
                    window.recordingSessionMetrics = {};
                    sessionManager.start();
                    
                    // Create retry tracker for failure recovery
                    const retryTracker = new RetryTracker({
                        uploadQueue: uploadQueue,
                        maxRetries: 5,
                        maxTotalBackoffMs: 5 * 60 * 1000,  // 5 minutes
                        onMetricsUpdate: (metrics) => {
                            if (window.recordingRetryMetrics) {
                                Object.assign(window.recordingRetryMetrics, metrics);
                            }
                        },
                    });
                    
                    window.recordingRetryTracker = retryTracker;
                    window.recordingRetryMetrics = {};
                    
                    // Wire upload queue to use retry tracker
                    uploadQueue.retryTracker = retryTracker;
                    retryTracker.start();
                    
                    // Wire encoder to upload queue
                    opusEncoder.onEncodedPacket = (packet) => {
                        uploadQueue.queuePacket(packet);
                        sessionManager.notifyChunkQueued(packet);
                        
                        // Also call handleEncodedPacket if defined
                        if (window.handleEncodedPacket) {
                            window.handleEncodedPacket(packet);
                        }
                    };
                    
                    // Update frame collector to emit frames to encoder
                    frameCollector.onFrameReady = (frame) => {
                        opusEncoder.encode(frame);
                    };
                    
                    // Set up message handler for PCM frames from worklet
                    workletNode.port.onmessage = (event) => {
                        if (event.data.type === "pcmFrame") {
                            // Pass PCM frame to collector for 5-second chunking
                            frameCollector.processPcmFrame(event.data);
                        }
                    };
                    
                    // Set up error handler
                    workletNode.port.onmessageerror = (event) => {
                        console.error(
                            "❌ AudioWorklet message error:",
                            event.error
                        );
                    };
                    
                    console.log(
                        "✅ AudioWorklet configured for PCM capture"
                    );
                    
                } catch (error) {
                    console.error(
                        "❌ Failed to set up AudioWorklet:",
                        error
                    );
                    
                    // Fall back to MediaRecorder
                    window.useOpusTransport = false;
                }
            }

            // ======================================================
            // CREATE MEDIA RECORDER (OLD PATH)
            // ======================================================

            const mixedStream =
                destination.stream;


            console.log(
                "🎙️ Recording audio tracks:",
                mixedStream.getAudioTracks().length
            );


            // Only create MediaRecorder if NOT using Opus transport
            let mediaRecorder = null;
            if (!useOpusTransport) {
                mediaRecorder =
                    new MediaRecorder(
                        mixedStream,
                        {
                            mimeType:
                                "audio/webm; codecs=opus"
                        }
                    );
            }


            window.mediaRecorder =
                mediaRecorder;


            // ======================================================
            // CHUNK STATE (OLD PATH ONLY)
            // ======================================================

            window.chunkCounter = 0;

            window.pendingAudioChunkPromises = [];


            // ======================================================
            // AUDIO CHUNKS (OLD PATH ONLY)
            // ======================================================
            
            // Only set up MediaRecorder listeners if using old path
            if (mediaRecorder) {

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

            } else {
                console.log(
                    "✅ AudioWorklet PCM capture started for:",
                    meetingId
                );
            }


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
    

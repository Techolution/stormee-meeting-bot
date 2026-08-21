    async () => {
        console.log("🛑 Stopping recording...");
        
        // ======================================================
        // CLEANUP OLD PATH (MediaRecorder)
        // ======================================================
        
        const recorder = window.mediaRecorder;

        if (recorder) {
            if (recorder.state === "inactive") {
                console.log("MediaRecorder already inactive");
            } else {
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
            }
            
            window.mediaRecorder = null;
        }
        
        // Wait for any pending MediaRecorder chunk uploads
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
        
        // ======================================================
        // CLEANUP NEW PATH (AudioWorklet + Opus)
        // ======================================================
        
        // Flush any remaining audio in the frame collector
        if (window.recordingFrameCollector) {
            try {
                const finalFrame = window.recordingFrameCollector.flush();
                if (finalFrame && window.handleOpusFrame) {
                    // Send final partial frame for encoding
                    window.handleOpusFrame(finalFrame);
                    console.log(
                        "✅ Final PCM frame flushed"
                    );
                }
                
                // Close the collector
                window.recordingFrameCollector.close();
            } catch (e) {
                console.warn(
                    "Failed to flush frame collector:",
                    e
                );
            }
            window.recordingFrameCollector = null;
            window.recordingFrameMetrics = null;
        }
        
        if (window.recordingAudioWorklet) {
            try {
                // Disconnect the worklet node
                window.recordingAudioWorklet.disconnect();
                console.log(
                    "🛑 AudioWorklet disconnected"
                );
            } catch (e) {
                console.warn(
                    "Failed to disconnect AudioWorklet:",
                    e
                );
            }
            window.recordingAudioWorklet = null;
        }
        
        if (window.recordingOpusEncoder) {
            try {
                // Close the encoder
                await window.recordingOpusEncoder.close();
                console.log(
                    "🛑 Opus encoder closed"
                );
            } catch (e) {
                console.warn(
                    "Failed to close Opus encoder:",
                    e
                );
            }
            window.recordingOpusEncoder = null;
            window.recordingEncoderMetrics = null;
        }
        
        // Flush and finalize session manager
        if (window.recordingSessionManager) {
            try {
                // Finalize current session
                await window.recordingSessionManager.finalizeCurrent();
                console.log(
                    "🛑 Upload session manager finalized"
                );
                
                // Stop the session manager
                window.recordingSessionManager.stop();
            } catch (e) {
                console.warn(
                    "Failed to finalize session manager:",
                    e
                );
            }
            window.recordingSessionManager = null;
            window.recordingSessionMetrics = null;
        }
        
        // Flush and finalize upload queue
        if (window.recordingUploadQueue) {
            try {
                // Wait for pending uploads to complete
                await window.recordingUploadQueue.flush();
                console.log(
                    "🛑 Upload queue flushed"
                );
                
                // Close the queue
                window.recordingUploadQueue.close();
            } catch (e) {
                console.warn(
                    "Failed to flush upload queue:",
                    e
                );
            }
            window.recordingUploadQueue = null;
            window.recordingUploadMetrics = null;
        }
        
        // Close and clean up retry tracker
        if (window.recordingRetryTracker) {
            try {
                window.recordingRetryTracker.close();
                console.log(
                    "🛑 Retry tracker closed"
                );
            } catch (e) {
                console.warn(
                    "Failed to close retry tracker:",
                    e
                );
            }
            window.recordingRetryTracker = null;
            window.recordingRetryMetrics = null;
        }
        
        if (window.recordingUploadSession) {
            try {
                // Finalize the upload session (to be implemented in future ACT)
                if (typeof window.recordingUploadSession.finalize === "function") {
                    await window.recordingUploadSession.finalize();
                    console.log(
                        "🛑 Upload session finalized"
                    );
                }
            } catch (e) {
                console.warn(
                    "Failed to finalize upload session:",
                    e
                );
            }
            window.recordingUploadSession = null;
        }
        
        // ======================================================
        // CLEANUP SHARED RESOURCES
        // ======================================================
        
        if (window.recordingDestination) {
            window.recordingDestination = null;
        }
        
        if (window.recordingAudioContext) {
            try {
                await window.recordingAudioContext.close();
                console.log(
                    "🛑 Recording audio context closed"
                );
            } catch (e) {
                console.warn(
                    "Failed to close AudioContext:",
                    e
                );
            }
            window.recordingAudioContext = null;
        }
        
        console.log(
            "✅ Recording cleanup complete"
        );
    }

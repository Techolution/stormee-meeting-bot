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

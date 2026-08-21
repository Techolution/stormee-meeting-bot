/**
 * PCM Frame Collector - Accumulates audio frames and emits 5-second logical transport chunks.
 * 
 * This class receives continuous PCM frames from the AudioWorklet and accumulates them
 * until reaching 5 seconds of audio duration (based on sample count, not wall-clock time).
 * When a 5-second boundary is crossed, it emits a complete frame for Opus encoding.
 * 
 * Key design:
 * - Sample-based duration calculation (deterministic, not affected by system clock)
 * - Supports different sample rates (16kHz, 48kHz, etc.)
 * - Tracks running totals for metrics and debugging
 * - Emits frames with complete metadata
 */

class PcmFrameCollector {
    /**
     * Initialize the frame collector.
     * 
     * @param {Object} config - Configuration object
     *   - sampleRate: Audio sample rate (16000, 48000, etc.)
     *   - channels: Number of channels (1 for mono, 2 for stereo)
     *   - onFrameReady: Callback when 5-second frame is ready
     *   - onMetricsUpdate: Optional callback for metrics updates
     */
    constructor(config) {
        this.sampleRate = config.sampleRate || 48000;
        this.channels = config.channels || 1;
        this.onFrameReady = config.onFrameReady;
        this.onMetricsUpdate = config.onMetricsUpdate;
        
        // Calculate the number of samples in 5 seconds
        this.FIVE_SECONDS_SAMPLES = this.sampleRate * 5;
        
        // Internal state
        this.frameNumber = 0;
        this.totalSamplesProcessed = 0;
        this.buffer = [];  // Array of PCM data chunks
        this.bufferedSamples = 0;  // Number of samples currently in buffer
        
        // Metrics
        this.framesEmitted = 0;
        this.bytesProcessed = 0;
        this.startTime = Date.now();
        
        console.log(
            `[PcmFrameCollector] Initialized: ` +
            `sampleRate=${this.sampleRate}Hz, ` +
            `channels=${this.channels}, ` +
            `5-second boundary=${this.FIVE_SECONDS_SAMPLES} samples`
        );
    }
    
    /**
     * Process an incoming PCM frame from the AudioWorklet.
     * 
     * Accumulates the frame data and checks if a 5-second boundary has been crossed.
     * If yes, emits a complete frame and resets the buffer.
     * 
     * @param {Object} pcmFrameData - Data from AudioWorklet processor
     *   - data: Float32Array with PCM audio
     *   - frameSize: Number of samples in this frame
     *   - sampleRate: Sample rate (for validation)
     *   - channels: Number of channels
     *   - durationMs: Duration reported by worklet
     *   - totalSamplesProcessed: Running sample count from worklet
     */
    processPcmFrame(pcmFrameData) {
        if (!pcmFrameData || !pcmFrameData.data) {
            console.warn(
                "[PcmFrameCollector] Received invalid PCM frame"
            );
            return;
        }
        
        const data = pcmFrameData.data;
        const frameSize = pcmFrameData.frameSize || data.length;
        
        // Validate sample rate hasn't changed
        if (pcmFrameData.sampleRate && pcmFrameData.sampleRate !== this.sampleRate) {
            console.warn(
                `[PcmFrameCollector] Sample rate mismatch: ` +
                `expected ${this.sampleRate}, got ${pcmFrameData.sampleRate}`
            );
        }
        
        // Add frame to buffer
        this.buffer.push(data);
        this.bufferedSamples += frameSize;
        this.totalSamplesProcessed += frameSize;
        this.bytesProcessed += data.byteLength || (frameSize * 4); // 4 bytes per float32
        
        // Check if we've crossed a 5-second boundary
        if (this.bufferedSamples >= this.FIVE_SECONDS_SAMPLES) {
            this._emitFrame();
        }
        
        // Periodic metrics update (every ~1 second)
        if (this.totalSamplesProcessed % this.sampleRate === 0) {
            this._updateMetrics();
        }
    }
    
    /**
     * Emit a complete 5-second frame for Opus encoding.
     * 
     * Combines all buffered PCM data, creates the transport frame with metadata,
     * and calls the onFrameReady callback.
     * 
     * @private
     */
    _emitFrame() {
        // Combine all buffered data into a single array
        const combinedData = this._combineBuffer();
        
        // Extract exactly 5 seconds worth of samples (in case we overshot)
        const sampleData = this._extractFiveSecondFrame(combinedData);
        
        const frame = {
            frameNumber: this.frameNumber++,
            sampleRate: this.sampleRate,
            channels: this.channels,
            sampleFormat: "float32",
            durationMs: 5000,
            sampleCount: this.FIVE_SECONDS_SAMPLES,
            totalSamplesProcessed: this.totalSamplesProcessed,
            data: sampleData,
            timestamp: new Date(),
            metrics: {
                framesEmitted: this.framesEmitted,
                bytesProcessed: this.bytesProcessed
            }
        };
        
        this.framesEmitted++;
        
        // Reset buffer for next frame
        const remainingSamples = this.bufferedSamples - this.FIVE_SECONDS_SAMPLES;
        this.buffer = this._extractRemainder(remainingSamples);
        this.bufferedSamples = remainingSamples;
        
        // Emit the frame
        if (this.onFrameReady) {
            try {
                this.onFrameReady(frame);
            } catch (error) {
                console.error(
                    "[PcmFrameCollector] onFrameReady callback failed:",
                    error
                );
            }
        }
        
        console.log(
            `[PcmFrameCollector] Emitted frame ${frame.frameNumber}: ` +
            `${frame.sampleCount} samples, ` +
            `${frame.durationMs}ms, ` +
            `remaining buffer: ${remainingSamples} samples`
        );
    }
    
    /**
     * Combine all buffered data into a single Float32Array.
     * 
     * @private
     * @returns {Float32Array} Combined PCM data
     */
    _combineBuffer() {
        if (this.buffer.length === 0) {
            return new Float32Array(0);
        }
        
        if (this.buffer.length === 1) {
            return this.buffer[0];
        }
        
        // Multiple arrays - need to combine
        const combined = new Float32Array(this.bufferedSamples);
        let offset = 0;
        
        for (const chunk of this.buffer) {
            combined.set(chunk, offset);
            offset += chunk.length;
        }
        
        return combined;
    }
    
    /**
     * Extract exactly 5 seconds of samples from the combined data.
     * 
     * @private
     * @param {Float32Array} data - Combined PCM data
     * @returns {Float32Array} Exactly FIVE_SECONDS_SAMPLES samples
     */
    _extractFiveSecondFrame(data) {
        if (data.length >= this.FIVE_SECONDS_SAMPLES) {
            return data.slice(0, this.FIVE_SECONDS_SAMPLES);
        } else {
            // Should not happen, but handle gracefully
            console.warn(
                `[PcmFrameCollector] Buffer smaller than 5 seconds: ` +
                `${data.length} < ${this.FIVE_SECONDS_SAMPLES}`
            );
            return data;
        }
    }
    
    /**
     * Extract remainder samples that exceed 5-second boundary.
     * 
     * These samples are kept for the next frame.
     * 
     * @private
     * @param {number} remainingSamples - Number of samples to extract
     * @returns {Array<Float32Array>} Buffer for next frame
     */
    _extractRemainder(remainingSamples) {
        if (remainingSamples <= 0) {
            return [];
        }
        
        const combined = this._combineBuffer();
        if (combined.length <= this.FIVE_SECONDS_SAMPLES) {
            return [];
        }
        
        const remainder = combined.slice(this.FIVE_SECONDS_SAMPLES);
        return remainder.length > 0 ? [remainder] : [];
    }
    
    /**
     * Update metrics and log status.
     * 
     * @private
     */
    _updateMetrics() {
        const elapsedSeconds = (Date.now() - this.startTime) / 1000;
        const calculatedDuration = this.totalSamplesProcessed / this.sampleRate;
        
        const metrics = {
            elapsedSeconds: elapsedSeconds.toFixed(2),
            calculatedDuration: calculatedDuration.toFixed(2),
            totalSamplesProcessed: this.totalSamplesProcessed,
            totalMegabytes: (this.bytesProcessed / (1024 * 1024)).toFixed(2),
            framesEmitted: this.framesEmitted,
            bufferedSamples: this.bufferedSamples,
            bufferedSeconds: (this.bufferedSamples / this.sampleRate).toFixed(2)
        };
        
        if (this.onMetricsUpdate) {
            try {
                this.onMetricsUpdate(metrics);
            } catch (error) {
                console.warn(
                    "[PcmFrameCollector] onMetricsUpdate callback failed:",
                    error
                );
            }
        }
    }
    
    /**
     * Flush any remaining audio in the buffer.
     * 
     * Called when recording stops to ensure the final partial frame
     * (less than 5 seconds) is not lost.
     * 
     * @returns {Object|null} Final frame if buffer has data, null otherwise
     */
    flush() {
        if (this.bufferedSamples === 0) {
            console.log(
                "[PcmFrameCollector] Buffer empty, nothing to flush"
            );
            return null;
        }
        
        const combinedData = this._combineBuffer();
        const actualSamples = combinedData.length;
        const actualDurationMs = (actualSamples / this.sampleRate) * 1000;
        
        const frame = {
            frameNumber: this.frameNumber++,
            sampleRate: this.sampleRate,
            channels: this.channels,
            sampleFormat: "float32",
            durationMs: actualDurationMs,
            sampleCount: actualSamples,
            totalSamplesProcessed: this.totalSamplesProcessed,
            data: combinedData,
            timestamp: new Date(),
            isFinal: true,  // Mark this as final partial frame
            metrics: {
                framesEmitted: this.framesEmitted + 1,
                bytesProcessed: this.bytesProcessed
            }
        };
        
        this.framesEmitted++;
        this.buffer = [];
        this.bufferedSamples = 0;
        
        console.log(
            `[PcmFrameCollector] Flushed final frame ${frame.frameNumber}: ` +
            `${frame.sampleCount} samples, ` +
            `${frame.durationMs.toFixed(0)}ms`
        );
        
        return frame;
    }
    
    /**
     * Get current metrics.
     * 
     * @returns {Object} Current metrics
     */
    getMetrics() {
        const elapsedSeconds = (Date.now() - this.startTime) / 1000;
        const calculatedDuration = this.totalSamplesProcessed / this.sampleRate;
        
        return {
            elapsedSeconds: elapsedSeconds.toFixed(2),
            calculatedDuration: calculatedDuration.toFixed(2),
            totalSamplesProcessed: this.totalSamplesProcessed,
            totalMegabytes: (this.bytesProcessed / (1024 * 1024)).toFixed(2),
            framesEmitted: this.framesEmitted,
            bufferedSamples: this.bufferedSamples,
            bufferedSeconds: (this.bufferedSamples / this.sampleRate).toFixed(2)
        };
    }
    
    /**
     * Close/cleanup the collector.
     */
    close() {
        this.buffer = [];
        this.bufferedSamples = 0;
        console.log(
            `[PcmFrameCollector] Closed after emitting ${this.framesEmitted} frames`
        );
    }
}


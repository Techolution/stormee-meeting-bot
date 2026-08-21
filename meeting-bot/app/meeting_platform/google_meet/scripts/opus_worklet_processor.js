/**
 * AudioWorklet Processor for capturing raw PCM audio.
 * 
 * This processor runs in a separate thread (AudioWorkletGlobalScope) and captures
 * mixed audio from the AudioContext. It extracts PCM frames continuously and posts
 * them to the main thread for further processing (Opus encoding, chunking, upload).
 * 
 * Key design principles:
 * - Minimal allocations on the audio thread
 * - No network requests or expensive operations
 * - Sample-based duration tracking (not setInterval)
 * - Explicit audio format metadata
 * - Low-latency frame extraction
 */

class OpusWorkletProcessor extends AudioWorkletProcessor {
    /**
     * Initialize the processor with explicit audio format tracking.
     * 
     * @param {Object} options - Processor options from createAudioWorkletNode()
     *   - processorOptions.sampleRate: The AudioContext sample rate (typically 16000 or 48000)
     *   - processorOptions.channels: Number of audio channels (1 for mono, 2 for stereo)
     */
    constructor(options) {
        super();
        
        this.sampleRate = options?.processorOptions?.sampleRate || 
                         sampleRate || // Fallback to global if available
                         48000;
        this.channels = options?.processorOptions?.channels || 1;
        this.sampleFormat = options?.processorOptions?.sampleFormat || "float32";
        
        // Track total samples processed for duration calculation
        this.totalSamplesProcessed = 0;
        
        // Per-channel sample buffers to convert from interleaved float to byte format
        this.sampleBuffers = new Array(this.channels);
        for (let i = 0; i < this.channels; i++) {
            this.sampleBuffers[i] = new Float32Array(1024);
        }
        
        console.log(
            `[OpusWorkletProcessor] Initialized: ` +
            `sampleRate=${this.sampleRate}Hz, ` +
            `channels=${this.channels}, ` +
            `format=${this.sampleFormat}`
        );
    }
    
    /**
     * Process audio frames continuously.
     * 
     * Called by the browser approximately every 128 samples (at 48kHz = ~2.67ms).
     * This is the core audio capture point.
     * 
     * @param {Float32Array[][]} inputs - Input audio data [channel][sample]
     * @param {Float32Array[][]} outputs - Output audio data (unused, we're capture-only)
     * @param {Object} parameters - Audio parameters (unused for now)
     * @returns {boolean} true to keep the processor alive
     */
    process(inputs, outputs, parameters) {
        const input = inputs[0];
        
        if (!input || input.length === 0) {
            // No audio data available
            return true;
        }
        
        // Get the current frame size (typically 128 samples)
        const frameSize = input[0].length;
        this.totalSamplesProcessed += frameSize;
        
        // Extract PCM data from all channels
        const pcmFrame = this.extractPcmFrame(input, frameSize);
        
        // Calculate duration in milliseconds
        const durationMs = (this.totalSamplesProcessed / this.sampleRate) * 1000;
        
        // Post the frame to the main thread
        // The main thread will handle chunking, Opus encoding, and upload
        this.port.postMessage({
            type: "pcmFrame",
            data: pcmFrame,
            frameSize: frameSize,
            channels: this.channels,
            sampleRate: this.sampleRate,
            sampleFormat: this.sampleFormat,
            durationMs: durationMs,
            totalSamplesProcessed: this.totalSamplesProcessed
        });
        
        return true; // Keep the processor alive
    }
    
    /**
     * Extract PCM data from the audio frame.
     * 
     * Converts from the AudioContext's Float32 format to the specified output format.
     * For now, we keep Float32 to avoid precision loss during encoding.
     * 
     * @param {Float32Array[]} input - Input channels
     * @param {number} frameSize - Number of samples per channel
     * @returns {ArrayBuffer|Float32Array} PCM audio data
     */
    extractPcmFrame(input, frameSize) {
        if (this.sampleFormat === "float32") {
            // Return raw Float32 data (most flexible for Opus encoder)
            if (this.channels === 1 && input[0]) {
                // Mono: return the first channel directly
                return input[0].slice(0, frameSize);
            } else if (this.channels === 2 && input[0] && input[1]) {
                // Stereo: interleave the two channels
                const interleaved = new Float32Array(frameSize * 2);
                for (let i = 0; i < frameSize; i++) {
                    interleaved[i * 2] = input[0][i];     // Left
                    interleaved[i * 2 + 1] = input[1][i]; // Right
                }
                return interleaved;
            } else {
                // Fallback: just use first channel
                return input[0]?.slice(0, frameSize) || new Float32Array(frameSize);
            }
        } else if (this.sampleFormat === "pcm16") {
            // Convert Float32 to PCM16 (signed 16-bit)
            // PCM16 range is -32768 to 32767
            if (this.channels === 1 && input[0]) {
                return this.float32ToPcm16(input[0], frameSize);
            } else if (this.channels === 2 && input[0] && input[1]) {
                // Interleave stereo and convert
                const pcm16Buffer = new Int16Array(frameSize * 2);
                for (let i = 0; i < frameSize; i++) {
                    pcm16Buffer[i * 2] = Math.max(-32768, Math.min(32767, input[0][i] * 32767));
                    pcm16Buffer[i * 2 + 1] = Math.max(-32768, Math.min(32767, input[1][i] * 32767));
                }
                return pcm16Buffer.buffer;
            } else {
                return this.float32ToPcm16(input[0], frameSize);
            }
        } else {
            // Unknown format, default to float32
            return input[0]?.slice(0, frameSize) || new Float32Array(frameSize);
        }
    }
    
    /**
     * Convert Float32 audio samples to PCM16 (signed 16-bit integers).
     * 
     * @param {Float32Array} float32Data - Input audio in Float32 range [-1, 1]
     * @param {number} samples - Number of samples to convert
     * @returns {ArrayBuffer} PCM16 audio data as bytes
     */
    float32ToPcm16(float32Data, samples) {
        const pcm16 = new Int16Array(samples);
        for (let i = 0; i < samples; i++) {
            // Clamp to [-1, 1] range and scale to int16 range
            const sample = Math.max(-1, Math.min(1, float32Data[i]));
            pcm16[i] = sample < 0 
                ? sample * 0x8000  // Negative: -1 → -32768
                : sample * 0x7FFF; // Positive: 1 → 32767
        }
        return pcm16.buffer;
    }
}

// Register this processor in the AudioWorkletGlobalScope
registerProcessor("opus-capture", OpusWorkletProcessor);


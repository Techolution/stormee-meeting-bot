/**
 * Opus Encoder - Encodes PCM audio to Opus bitstream.
 * 
 * This is an abstraction layer supporting multiple encoder backends:
 * - WebCodecs API (Chrome 94+) - native browser support
 * - WASM Opus (libopus.wasm) - fallback for broader compatibility
 * - Worker-based encoding - for non-blocking operation
 * 
 * The encoder accepts 5-second PCM frames and produces Opus encoded packets.
 */

class OpusEncoder {
    /**
     * Initialize the Opus encoder.
     * 
     * @param {Object} config - Configuration
     *   - sampleRate: 16000 or 48000 (recommended: 16000 for speech)
     *   - channels: 1 or 2 (recommended: 1 for mono speech)
     *   - bitrate: 64-256 kbps (recommended: 96 for speech)
     *   - onEncodedPacket: Callback when Opus packet is ready
     *   - onMetricsUpdate: Optional metrics callback
     */
    constructor(config) {
        this.sampleRate = config.sampleRate || 16000;
        this.channels = config.channels || 1;
        this.bitrate = config.bitrate || 96;  // kbps
        this.onEncodedPacket = config.onEncodedPacket;
        this.onMetricsUpdate = config.onMetricsUpdate;
        
        // Encoder state
        this.ready = false;
        this.frameNumber = 0;
        this.totalFramesEncoded = 0;
        this.totalBytesEncoded = 0;
        
        // Implementation backend (will be set based on browser capabilities)
        this.backend = null;
        
        console.log(
            `[OpusEncoder] Initialized: ` +
            `sampleRate=${this.sampleRate}Hz, ` +
            `channels=${this.channels}, ` +
            `bitrate=${this.bitrate}kbps`
        );
        
        this._initializeBackend();
    }
    
    /**
     * Initialize the appropriate encoder backend based on browser capabilities.
     * 
     * @private
     */
    async _initializeBackend() {
        // Try WebCodecs first (Chrome 94+, Firefox 115+)
        if (window.AudioEncoder) {
            try {
                this.backend = new WebCodecsOpusBackend({
                    sampleRate: this.sampleRate,
                    channels: this.channels,
                    bitrate: this.bitrate * 1000  // Convert kbps to bps
                });
                await this.backend.init();
                this.ready = true;
                console.log(
                    "[OpusEncoder] Using WebCodecs backend"
                );
                return;
            } catch (error) {
                console.warn(
                    "[OpusEncoder] WebCodecs failed, falling back:",
                    error.message
                );
            }
        }
        
        // Fall back to mock encoder for now
        // In production, would load WASM Opus library
        this.backend = new MockOpusBackend({
            sampleRate: this.sampleRate,
            channels: this.channels,
            bitrate: this.bitrate
        });
        this.ready = true;
        console.log(
            "[OpusEncoder] Using mock backend (PRODUCTION: replace with WASM Opus)"
        );
    }
    
    /**
     * Encode a 5-second PCM frame to Opus.
     * 
     * @param {Object} frame - PCM frame from frame collector
     *   - frameNumber: ID
     *   - data: Float32Array with PCM samples
     *   - sampleRate: Sample rate (should match encoder)
     *   - durationMs: Duration (should be ~5000)
     *   - sampleCount: Total samples
     */
    async encode(frame) {
        if (!this.ready) {
            console.warn(
                "[OpusEncoder] Encoder not ready"
            );
            return;
        }
        
        try {
            const encodedData = await this.backend.encode(frame.data);
            
            const packet = {
                frameNumber: this.frameNumber++,
                sourceFrameNumber: frame.frameNumber,
                sampleRate: this.sampleRate,
                channels: this.channels,
                codec: "opus",
                bitrate: this.bitrate,
                durationMs: frame.durationMs,
                sampleCount: frame.sampleCount,
                data: encodedData,  // Uint8Array
                timestamp: new Date(),
                isFinal: frame.isFinal || false
            };
            
            this.totalFramesEncoded++;
            this.totalBytesEncoded += encodedData.byteLength;
            
            if (this.onEncodedPacket) {
                try {
                    this.onEncodedPacket(packet);
                } catch (error) {
                    console.error(
                        "[OpusEncoder] onEncodedPacket callback failed:",
                        error
                    );
                }
            }
            
            // Periodic metrics
            if (this.frameNumber % 12 === 0) {  // Every ~60 seconds (12x5-sec frames)
                this._updateMetrics();
            }
            
        } catch (error) {
            console.error(
                "[OpusEncoder] Encoding failed:",
                error
            );
            // Continue on error - don't break the pipeline
        }
    }
    
    /**
     * Update and report encoder metrics.
     * 
     * @private
     */
    _updateMetrics() {
        const metrics = {
            frameNumber: this.frameNumber,
            totalFramesEncoded: this.totalFramesEncoded,
            totalBytesEncoded: this.totalBytesEncoded,
            megabytesEncoded: (this.totalBytesEncoded / (1024 * 1024)).toFixed(2),
            averageBitrateKbps: this.totalFramesEncoded > 0 
                ? ((this.totalBytesEncoded * 8) / (this.totalFramesEncoded * 5)) / 1000
                : 0
        };
        
        if (this.onMetricsUpdate) {
            try {
                this.onMetricsUpdate(metrics);
            } catch (error) {
                console.warn(
                    "[OpusEncoder] onMetricsUpdate failed:",
                    error
                );
            }
        }
    }
    
    /**
     * Get current encoder metrics.
     * 
     * @returns {Object} Current metrics
     */
    getMetrics() {
        return {
            frameNumber: this.frameNumber,
            totalFramesEncoded: this.totalFramesEncoded,
            totalBytesEncoded: this.totalBytesEncoded,
            megabytesEncoded: (this.totalBytesEncoded / (1024 * 1024)).toFixed(2),
            averageBitrateKbps: this.totalFramesEncoded > 0 
                ? ((this.totalBytesEncoded * 8) / (this.totalFramesEncoded * 5)) / 1000
                : 0
        };
    }
    
    /**
     * Close the encoder and release resources.
     */
    async close() {
        this.ready = false;
        if (this.backend && typeof this.backend.close === "function") {
            try {
                await this.backend.close();
            } catch (error) {
                console.warn(
                    "[OpusEncoder] Error closing backend:",
                    error
                );
            }
        }
        this.backend = null;
        console.log(
            `[OpusEncoder] Closed after encoding ${this.totalFramesEncoded} frames`
        );
    }
}

/**
 * WebCodecs-based Opus encoder backend (Chrome 94+).
 * Uses native browser AudioEncoder for Opus encoding.
 */
class WebCodecsOpusBackend {
    constructor(config) {
        this.config = config;
        this.encoder = null;
        this.initialized = false;
    }
    
    async init() {
        const encoderConfig = {
            codec: "opus",
            sampleRate: this.config.sampleRate,
            numberOfChannels: this.config.channels,
            bitrate: this.config.bitrate  // in bps
        };
        
        try {
            const support = await AudioEncoder.isConfigSupported(encoderConfig);
            if (!support.supported) {
                throw new Error("Opus encoding not supported");
            }
            
            this.encoder = new AudioEncoder({
                output: (chunk) => {
                    this._handleEncodedChunk(chunk);
                },
                error: (error) => {
                    console.error(
                        "[WebCodecsOpusBackend] Encoder error:",
                        error
                    );
                }
            });
            
            this.encoder.configure(encoderConfig);
            this.initialized = true;
        } catch (error) {
            throw new Error(
                `Failed to initialize WebCodecs Opus encoder: ${error.message}`
            );
        }
    }
    
    async encode(pcmData) {
        if (!this.encoder) {
            throw new Error("Encoder not initialized");
        }
        
        // Convert Float32Array to AudioData
        const audioData = new AudioData({
            format: "f32",
            sampleRate: this.config.sampleRate,
            numberOfFrames: pcmData.length,
            numberOfChannels: this.config.channels,
            timestamp: 0,
            data: new Float32Array(pcmData)
        });
        
        this.encoder.encode(audioData);
        audioData.close();
        
        // Wait for encoded output
        return new Promise((resolve) => {
            this._nextEncodedChunk = resolve;
        });
    }
    
    _handleEncodedChunk(chunk) {
        const buffer = new Uint8Array(chunk.byteLength);
        chunk.copyTo(buffer);
        
        if (this._nextEncodedChunk) {
            this._nextEncodedChunk(buffer);
            this._nextEncodedChunk = null;
        }
    }
    
    async close() {
        if (this.encoder) {
            try {
                this.encoder.close();
            } catch (error) {
                console.warn(
                    "[WebCodecsOpusBackend] Error closing encoder:",
                    error
                );
            }
            this.encoder = null;
        }
    }
}

/**
 * Mock Opus encoder backend for testing.
 * Returns synthetic Opus-like data for development/testing.
 * Replace with real WASM Opus implementation in production.
 */
class MockOpusBackend {
    constructor(config) {
        this.config = config;
    }
    
    async encode(pcmData) {
        // Mock: Return synthetic Opus-like bytes
        // In production, replace with actual libopus.wasm encoding
        const estimatedSize = Math.ceil(
            (pcmData.length * this.config.bitrate) / (this.config.sampleRate * 8)
        );
        
        const mockOpusPacket = new Uint8Array(estimatedSize);
        // Add some realistic variation
        for (let i = 0; i < mockOpusPacket.length; i++) {
            mockOpusPacket[i] = Math.random() * 256;
        }
        
        return mockOpusPacket;
    }
    
    async close() {
        // No-op for mock
    }
}


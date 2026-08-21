/**
 * Upload Queue Manager - Manages Opus packet queuing and sequence numbering.
 * 
 * Receives encoded Opus packets, assigns global sequence numbers, and creates
 * transport chunks ready for resumable upload. Handles retries, idempotency,
 * and backpressure control.
 */

class UploadQueueManager {
    /**
     * Initialize the upload queue manager.
     * 
     * @param {Object} config - Configuration
     *   - meetingId: Meeting identifier
     *   - onChunkReady: Callback when chunk is ready for upload
     *   - maxQueueSize: Maximum bytes in queue (default: 10MB)
     *   - onMetricsUpdate: Optional metrics callback
     *   - retryTracker: Optional RetryTracker instance for retry coordination
     */
    constructor(config) {
        this.meetingId = config.meetingId;
        this.onChunkReady = config.onChunkReady;
        this.maxQueueSize = config.maxQueueSize || (10 * 1024 * 1024);  // 10MB default
        this.onMetricsUpdate = config.onMetricsUpdate;
        this.retryTracker = config.retryTracker || null;
        
        // Queue state
        this.queue = [];  // Array of pending chunks
        this.queueSize = 0;  // Total bytes in queue
        this.globalSequence = 0;  // Global sequence counter
        this.uploadSessionId = this._generateSessionId();
        
        // Upload tracking
        this.uploadedSequences = new Set();  // Uploaded sequence numbers
        this.failedSequences = new Map();    // Failed sequence → retry count
        this.pendingSequences = new Set();   // Currently uploading
        
        // Metrics
        this.totalChunksQueued = 0;
        this.totalChunksUploaded = 0;
        this.totalBytesSent = 0;
        this.totalRetries = 0;
        
        console.log(
            `[UploadQueueManager] Initialized for meeting ${this.meetingId}, ` +
            `session ${this.uploadSessionId}, ` +
            `max queue ${this.maxQueueSize / (1024 * 1024)}MB`
        );
    }
    
    /**
     * Generate a unique session ID for this 5-minute session.
     * @private
     */
    _generateSessionId() {
        const timestamp = Date.now();
        const random = Math.random().toString(36).substr(2, 9);
        return `${timestamp}-${random}`;
    }
    
    /**
     * Queue an Opus encoded packet for upload.
     * 
     * @param {Object} packet - Opus packet from encoder
     *   - data: Uint8Array with Opus bytes
     *   - durationMs: Duration of this packet
     *   - sampleRate: Sample rate
     *   - channels: Number of channels
     *   - isFinal: true if final partial segment
     */
    queuePacket(packet) {
        if (!packet || !packet.data) {
            console.warn(
                "[UploadQueueManager] Invalid packet received"
            );
            return;
        }
        
        // Check queue capacity
        if (this.queueSize + packet.data.byteLength > this.maxQueueSize) {
            console.warn(
                `[UploadQueueManager] Queue full (${(this.queueSize / (1024 * 1024)).toFixed(2)}MB), ` +
                `dropping packet to prevent memory overflow`
            );
            return;
        }
        
        // Create transport chunk
        const chunk = {
            meetingId: this.meetingId,
            uploadSessionId: this.uploadSessionId,
            sequenceNumber: this.globalSequence++,
            codec: "opus",
            sampleRate: packet.sampleRate,
            channels: packet.channels,
            durationMs: packet.durationMs,
            data: packet.data,
            timestamp: packet.timestamp || new Date(),
            isFinal: packet.isFinal || false
        };
        
        this.queue.push(chunk);
        this.queueSize += packet.data.byteLength;
        this.totalChunksQueued++;
        this.pendingSequences.add(chunk.sequenceNumber);
        
        console.log(
            `[UploadQueueManager] Queued chunk seq=${chunk.sequenceNumber}, ` +
            `size=${(packet.data.byteLength / 1024).toFixed(1)}KB, ` +
            `queue=${(this.queueSize / (1024 * 1024)).toFixed(2)}MB, ` +
            `final=${chunk.isFinal}`
        );
        
        // Process queue
        this._processQueue();
    }
    
    /**
     * Process queue and emit chunks ready for upload.
     * @private
     */
    _processQueue() {
        while (this.queue.length > 0) {
            const chunk = this.queue[0];
            
            // Don't upload if already uploaded or pending retry
            if (this.uploadedSequences.has(chunk.sequenceNumber)) {
                this.queue.shift();
                this.queueSize -= chunk.data.byteLength;
                continue;
            }
            
            // Try to upload
            try {
                this._uploadChunk(chunk);
                this.queue.shift();
                this.queueSize -= chunk.data.byteLength;
            } catch (error) {
                // Stop processing if upload fails
                console.warn(
                    `[UploadQueueManager] Upload failed for seq=${chunk.sequenceNumber}: ${error.message}`
                );
                break;
            }
        }
        
        this._updateMetrics();
    }
    
    /**
     * Upload a single chunk using sendAudioChunkToPython.
     * @private
     */
    _uploadChunk(chunk) {
        // Convert Uint8Array to Array for JSON serialization
        const audioBlob = Array.from(chunk.data);
        
        const payload = {
            meetingId: chunk.meetingId,
            uploadSessionId: chunk.uploadSessionId,
            sequenceNumber: chunk.sequenceNumber,
            codec: chunk.codec,
            sampleRate: chunk.sampleRate,
            channels: chunk.channels,
            durationMs: chunk.durationMs,
            audioBlob: audioBlob,
            timestamp: chunk.timestamp.toISOString(),
            isFinal: chunk.isFinal,
            audioFormatVersion: 2  // Indicate new Opus transport format
        };
        
        // Call existing Python binding
        if (!window.sendAudioChunkToPython) {
            throw new Error("sendAudioChunkToPython not available");
        }
        
        // Fire-and-forget with error handling
        Promise.resolve(window.sendAudioChunkToPython(payload))
            .then(() => {
                this.uploadedSequences.add(chunk.sequenceNumber);
                this.pendingSequences.delete(chunk.sequenceNumber);
                this.totalChunksUploaded++;
                this.totalBytesSent += chunk.data.byteLength;
                
                // Clear failed count on success
                this.failedSequences.delete(chunk.sequenceNumber);
                
                // Notify retry tracker of success
                if (this.retryTracker) {
                    this.retryTracker.recordSuccess(
                        chunk.uploadSessionId,
                        chunk.sequenceNumber
                    );
                }
                
                console.log(
                    `[UploadQueueManager] Uploaded seq=${chunk.sequenceNumber}, ` +
                    `total sent=${(this.totalBytesSent / (1024 * 1024)).toFixed(2)}MB`
                );
            })
            .catch((error) => {
                this.pendingSequences.delete(chunk.sequenceNumber);
                
                const retries = this.failedSequences.get(chunk.sequenceNumber) || 0;
                this.failedSequences.set(chunk.sequenceNumber, retries + 1);
                this.totalRetries++;
                
                console.error(
                    `[UploadQueueManager] Upload failed seq=${chunk.sequenceNumber}, ` +
                    `attempt ${retries + 1}: ${error.message}`
                );
                
                // Notify retry tracker of failure
                if (this.retryTracker) {
                    const willRetry = this.retryTracker.recordFailure(
                        chunk.uploadSessionId,
                        chunk.sequenceNumber,
                        error
                    );
                    
                    // Only re-queue if retry tracker says to retry
                    if (willRetry) {
                        this.queue.push(chunk);
                    }
                } else {
                    // Fallback: re-queue for retry without tracker
                    this.queue.push(chunk);
                }
            });
    }
    
    /**
     * Get chunks awaiting upload.
     * @returns {Array} Queue of pending chunks
     */
    getPendingChunks() {
        return this.queue.filter((chunk) => !this.uploadedSequences.has(chunk.sequenceNumber));
    }
    
    /**
     * Get upload status for a specific sequence.
     * @returns {string} "pending", "uploaded", "failed", or "unknown"
     */
    getSequenceStatus(sequenceNumber) {
        if (this.uploadedSequences.has(sequenceNumber)) return "uploaded";
        if (this.failedSequences.has(sequenceNumber)) return "failed";
        if (this.pendingSequences.has(sequenceNumber)) return "pending";
        return "unknown";
    }
    
    /**
     * Flush all pending chunks (for recording stop).
     * @returns {Promise} Resolves when all chunks uploaded or retried
     */
    async flush() {
        console.log(
            `[UploadQueueManager] Flushing ${this.queue.length} pending chunks`
        );
        
        // Wait for all pending uploads
        const maxWaitMs = 30000;  // 30 second timeout
        const startTime = Date.now();
        
        while (this.pendingSequences.size > 0 && Date.now() - startTime < maxWaitMs) {
            await new Promise((resolve) => setTimeout(resolve, 100));
        }
        
        if (this.pendingSequences.size > 0) {
            console.warn(
                `[UploadQueueManager] Flush timeout with ${this.pendingSequences.size} pending uploads`
            );
        }
        
        const metrics = this.getMetrics();
        console.log(
            `[UploadQueueManager] Flush complete: ${metrics.totalChunksUploaded} uploaded, ` +
            `${this.failedSequences.size} failed, ` +
            `${this.queue.length} still queued`
        );
    }
    
    /**
     * Update metrics.
     * @private
     */
    _updateMetrics() {
        const metrics = this.getMetrics();
        
        if (this.onMetricsUpdate) {
            try {
                this.onMetricsUpdate(metrics);
            } catch (error) {
                console.warn(
                    "[UploadQueueManager] onMetricsUpdate failed:",
                    error
                );
            }
        }
    }
    
    /**
     * Get current metrics.
     * @returns {Object} Metrics
     */
    getMetrics() {
        return {
            sessionId: this.uploadSessionId,
            globalSequence: this.globalSequence,
            totalChunksQueued: this.totalChunksQueued,
            totalChunksUploaded: this.totalChunksUploaded,
            totalBytesSent: this.totalBytesSent,
            totalRetries: this.totalRetries,
            queueDepth: this.queue.length,
            queueSizeMB: (this.queueSize / (1024 * 1024)).toFixed(2),
            pendingUploads: this.pendingSequences.size,
            failedChunks: this.failedSequences.size,
            successRate: this.totalChunksQueued > 0 
                ? ((this.totalChunksUploaded / this.totalChunksQueued) * 100).toFixed(1) + "%"
                : "0%"
        };
    }
    
    /**
     * Rotate to new session (for 5-minute boundaries).
     * Should be called from session manager.
     */
    rotateSession() {
        const oldSessionId = this.uploadSessionId;
        this.uploadSessionId = this._generateSessionId();
        
        // Keep global sequence across sessions
        // Reset per-session tracking
        this.uploadedSequences.clear();
        this.failedSequences.clear();
        this.pendingSequences.clear();
        
        console.log(
            `[UploadQueueManager] Rotated to new session: ${this.uploadSessionId} ` +
            `(was ${oldSessionId})`
        );
    }
    
    /**
     * Close the queue manager.
     */
    close() {
        this.queue = [];
        this.queueSize = 0;
        console.log(
            `[UploadQueueManager] Closed after queuing ${this.totalChunksQueued} chunks`
        );
    }
}


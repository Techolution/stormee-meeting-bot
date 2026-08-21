/**
 * Retry Tracker - Frontend companion to RetryManager.
 * 
 * Tracks failed chunks and implements exponential backoff matching backend logic.
 * Coordinates retries with upload queue to prevent cascade failures.
 */

class RetryTracker {
    /**
     * Initialize retry tracker.
     * 
     * @param {Object} config - Configuration
     *   - uploadQueue: UploadQueueManager instance (for retry scheduling)
     *   - maxRetries: Maximum retry attempts (default: 5)
     *   - maxTotalBackoffMs: Maximum total backoff time (default: 300000)
     *   - onMetricsUpdate: Optional metrics callback
     */
    constructor(config) {
        this.uploadQueue = config.uploadQueue;
        this.maxRetries = config.maxRetries || 5;
        this.maxTotalBackoffMs = config.maxTotalBackoffMs || (5 * 60 * 1000);  // 5 minutes
        this.onMetricsUpdate = config.onMetricsUpdate;
        
        // Retry tracking: sessionId:sequenceNumber -> retry state
        this.retryQueue = new Map();
        
        // Metrics
        this.totalRetriesAttempted = 0;
        this.totalRetriesSucceeded = 0;
        this.totalRetryFailed = 0;
        this.chunksPermanentlyFailed = 0;
        
        // Retry processing timer
        this.retryProcessTimer = null;
        this.isProcessing = false;
        
        console.log(
            "[RetryTracker] Initialized, " +
            `max_retries=${this.maxRetries}, ` +
            `max_backoff=${this.maxTotalBackoffMs}ms`
        );
    }
    
    /**
     * Start retry processing loop.
     */
    start() {
        if (this.retryProcessTimer) {
            console.warn("[RetryTracker] Already running");
            return;
        }
        
        // Check for retryable chunks every 100ms
        this.retryProcessTimer = setInterval(() => {
            this._processRetries();
        }, 100);
        
        console.log("[RetryTracker] Started");
    }
    
    /**
     * Stop retry processing.
     */
    stop() {
        if (this.retryProcessTimer) {
            clearInterval(this.retryProcessTimer);
            this.retryProcessTimer = null;
        }
        
        console.log(
            `[RetryTracker] Stopped with ${this.retryQueue.size} pending retries`
        );
    }
    
    /**
     * Classify error as transient or permanent.
     * 
     * @param {Error} error - Exception
     * @param {number} httpStatus - HTTP status code (if available)
     * @returns {string} "transient", "permanent", or "unknown"
     */
    classifyError(error, httpStatus) {
        if (httpStatus) {
            // HTTP 5xx and 429 are transient
            if ((httpStatus >= 500 && httpStatus < 600) || httpStatus === 429) {
                return "transient";
            }
            // HTTP 4xx (except 429) are permanent
            if (httpStatus >= 400 && httpStatus < 500) {
                return "permanent";
            }
        }
        
        // Classify by error message
        const errorMsg = (error?.message || error?.toString() || "").toLowerCase();
        if (
            errorMsg.includes("timeout") ||
            errorMsg.includes("connection") ||
            errorMsg.includes("network") ||
            errorMsg.includes("refused")
        ) {
            return "transient";
        }
        
        // Default to transient (better to retry than lose data)
        return "unknown";
    }
    
    /**
     * Get exponential backoff duration.
     * 
     * @param {number} attempt - Attempt number (0-indexed)
     * @returns {number} Backoff duration in milliseconds
     */
    getBackoffMs(attempt) {
        const baseMs = 1000;  // 1 second
        const exponent = Math.min(attempt, 4);  // Cap at 2^4 = 16s
        const backoffMs = baseMs * Math.pow(2, exponent);
        return Math.min(backoffMs, 30000);  // Cap at 30 seconds
    }
    
    /**
     * Record chunk upload failure.
     * 
     * @param {string} sessionId - Session ID
     * @param {number} sequenceNumber - Chunk sequence number
     * @param {Error} error - Exception
     * @param {number} httpStatus - HTTP status (optional)
     * @returns {boolean} true if will retry, false if exhausted
     */
    recordFailure(sessionId, sequenceNumber, error, httpStatus) {
        const key = `${sessionId}:${sequenceNumber}`;
        
        // Get or create retry entry
        let retryState = this.retryQueue.get(key);
        if (!retryState) {
            retryState = {
                sessionId: sessionId,
                sequenceNumber: sequenceNumber,
                attempt: 0,
                firstFailureAt: Date.now(),
                lastAttemptAt: null,
                nextRetryAt: null,
                errorClassification: "unknown",
                errorMessage: "",
                totalBackoffMs: 0,
            };
            this.retryQueue.set(key, retryState);
        }
        
        // Update retry state
        retryState.attempt++;
        retryState.lastAttemptAt = Date.now();
        retryState.errorClassification = this.classifyError(error, httpStatus);
        retryState.errorMessage = error?.message || String(error);
        
        // Check if permanent failure
        if (retryState.errorClassification === "permanent") {
            console.warn(
                `[RetryTracker] Permanent failure for seq=${sequenceNumber}: ` +
                retryState.errorMessage
            );
            this.chunksPermanentlyFailed++;
            this.retryQueue.delete(key);
            return false;
        }
        
        // Check if max retries exceeded
        if (retryState.attempt > this.maxRetries) {
            console.error(
                `[RetryTracker] Exhausted retries for seq=${sequenceNumber} ` +
                `after ${retryState.attempt} attempts`
            );
            this.chunksPermanentlyFailed++;
            this.retryQueue.delete(key);
            return false;
        }
        
        // Check if total backoff exceeded
        if (retryState.totalBackoffMs > this.maxTotalBackoffMs) {
            console.error(
                `[RetryTracker] Exceeded max backoff for seq=${sequenceNumber} ` +
                `(${retryState.totalBackoffMs}ms > ${this.maxTotalBackoffMs}ms)`
            );
            this.chunksPermanentlyFailed++;
            this.retryQueue.delete(key);
            return false;
        }
        
        // Schedule retry
        const backoffMs = this.getBackoffMs(retryState.attempt - 1);
        retryState.nextRetryAt = Date.now() + backoffMs;
        retryState.totalBackoffMs += backoffMs;
        this.totalRetriesAttempted++;
        
        console.log(
            `[RetryTracker] Scheduled retry for seq=${sequenceNumber}, ` +
            `attempt=${retryState.attempt}, ` +
            `next_retry_in=${backoffMs}ms`
        );
        
        this._updateMetrics();
        return true;
    }
    
    /**
     * Record successful upload.
     * 
     * @param {string} sessionId - Session ID
     * @param {number} sequenceNumber - Chunk sequence number
     */
    recordSuccess(sessionId, sequenceNumber) {
        const key = `${sessionId}:${sequenceNumber}`;
        const retryState = this.retryQueue.get(key);
        
        if (retryState && retryState.attempt > 0) {
            console.log(
                `[RetryTracker] Retry successful for seq=${sequenceNumber} ` +
                `after ${retryState.attempt} attempts`
            );
            this.totalRetriesSucceeded++;
        }
        
        this.retryQueue.delete(key);
        this._updateMetrics();
    }
    
    /**
     * Process retries: re-queue chunks that are ready.
     * @private
     */
    _processRetries() {
        if (this.isProcessing || !this.uploadQueue) {
            return;
        }
        
        this.isProcessing = true;
        
        try {
            const now = Date.now();
            const toRetry = [];
            
            for (const [key, retryState] of this.retryQueue.entries()) {
                // Check if ready to retry
                if (retryState.nextRetryAt && now >= retryState.nextRetryAt) {
                    toRetry.push(retryState);
                }
            }
            
            // Re-queue retryable chunks
            for (const retryState of toRetry) {
                // Note: This is a placeholder - in practice, we'd need to re-fetch
                // the chunk data from storage and re-queue it. For now, we just
                // update the tracking state.
                console.log(
                    `[RetryTracker] Retrying seq=${retryState.sequenceNumber} ` +
                    `(attempt ${retryState.attempt})`
                );
            }
        } finally {
            this.isProcessing = false;
        }
    }
    
    /**
     * Update metrics.
     * @private
     */
    _updateMetrics() {
        if (this.onMetricsUpdate) {
            try {
                this.onMetricsUpdate(this.getMetrics());
            } catch (error) {
                console.warn(
                    "[RetryTracker] onMetricsUpdate failed:",
                    error
                );
            }
        }
    }
    
    /**
     * Get retry metrics.
     * @returns {Object} Metrics
     */
    getMetrics() {
        return {
            queueSize: this.retryQueue.size,
            totalRetriesAttempted: this.totalRetriesAttempted,
            totalRetriesSucceeded: this.totalRetriesSucceeded,
            totalRetryFailed: this.totalRetryFailed,
            chunksPermanentlyFailed: this.chunksPermanentlyFailed,
            failureRate: (
                this.totalRetriesAttempted > 0
                    ? ((this.totalRetryFailed / this.totalRetriesAttempted) * 100).toFixed(1) + "%"
                    : "0%"
            ),
        };
    }
    
    /**
     * Get recovery state snapshot.
     * @returns {Object} Recovery info
     */
    getRecoveryState() {
        return {
            timestamp: new Date().toISOString(),
            pendingRetries: Array.from(this.retryQueue.values()).map((state) => ({
                sessionId: state.sessionId,
                sequenceNumber: state.sequenceNumber,
                attempt: state.attempt,
                nextRetryAt: new Date(state.nextRetryAt).toISOString(),
            })),
            metrics: this.getMetrics(),
        };
    }
    
    /**
     * Close the retry tracker.
     */
    close() {
        this.stop();
        this.retryQueue.clear();
        console.log(
            `[RetryTracker] Closed after ${this.totalRetriesAttempted} total retries`
        );
    }
}


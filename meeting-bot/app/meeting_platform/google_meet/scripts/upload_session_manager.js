/**
 * Upload Session Manager - Manages 5-minute session boundaries and coordination.
 * 
 * Rotates upload sessions every 5 minutes, emits finalization events to backend,
 * and maintains session metadata for recovery and observability.
 */

class UploadSessionManager {
    /**
     * Initialize the session manager.
     * 
     * @param {Object} config - Configuration
     *   - meetingId: Meeting identifier
     *   - uploadQueue: UploadQueueManager instance
     *   - onSessionFinalized: Callback when session completes (5 min or stop)
     *   - onMetricsUpdate: Optional metrics callback
     *   - sessionDurationMs: Session duration (default: 5 * 60 * 1000 = 5 minutes)
     */
    constructor(config) {
        this.meetingId = config.meetingId;
        this.uploadQueue = config.uploadQueue;
        this.onSessionFinalized = config.onSessionFinalized;
        this.onMetricsUpdate = config.onMetricsUpdate;
        this.sessionDurationMs = config.sessionDurationMs || (5 * 60 * 1000);
        
        // Session state
        this.activeSession = null;
        this.sessionHistory = [];
        this.sessionRotationTimer = null;
        this.isRunning = false;
        
        // Metrics
        this.totalSessions = 0;
        this.totalChunksInSessions = 0;
        this.totalBytesInSessions = 0;
        
        console.log(
            `[UploadSessionManager] Initialized for meeting ${this.meetingId}, ` +
            `session duration ${(this.sessionDurationMs / 1000)}s`
        );
    }
    
    /**
     * Start the session manager and begin the first session.
     */
    start() {
        if (this.isRunning) {
            console.warn("[UploadSessionManager] Already running");
            return;
        }
        
        this.isRunning = true;
        this._startNewSession();
        console.log("[UploadSessionManager] Started");
    }
    
    /**
     * Start a new session.
     * @private
     */
    _startNewSession() {
        const previousSession = this.activeSession;
        
        // Create new session
        this.activeSession = {
            sessionId: this.uploadQueue.uploadSessionId,
            meetingId: this.meetingId,
            startTime: new Date(),
            startSequence: this.uploadQueue.globalSequence,
            endSequence: null,
            chunksInSession: 0,
            bytesInSession: 0,
            status: "active"
        };
        
        console.log(
            `[UploadSessionManager] Started new session: ${this.activeSession.sessionId}, ` +
            `starting at sequence ${this.activeSession.startSequence}`
        );
        
        // Schedule next rotation
        if (this.sessionRotationTimer) {
            clearTimeout(this.sessionRotationTimer);
        }
        
        this.sessionRotationTimer = setTimeout(() => {
            this._rotateSession();
        }, this.sessionDurationMs);
        
        this._updateMetrics();
    }
    
    /**
     * Rotate to next session (called every 5 minutes).
     * @private
     */
    _rotateSession() {
        if (!this.activeSession) {
            return;
        }
        
        // Finalize current session
        this.activeSession.endSequence = this.uploadQueue.globalSequence;
        this.activeSession.status = "finalized";
        
        console.log(
            `[UploadSessionManager] Rotating session ${this.activeSession.sessionId}, ` +
            `sequences ${this.activeSession.startSequence}-${this.activeSession.endSequence}`
        );
        
        // Emit finalization
        this._emitSessionFinalization(this.activeSession);
        
        // Save to history
        this.sessionHistory.push(this.activeSession);
        this.totalSessions++;
        
        // Rotate queue's session ID
        this.uploadQueue.rotateSession();
        
        // Start new session
        this._startNewSession();
    }
    
    /**
     * Emit session finalization event.
     * @private
     */
    _emitSessionFinalization(session) {
        const sessionData = {
            meetingId: session.meetingId,
            uploadSessionId: session.sessionId,
            startTime: session.startTime.toISOString(),
            endTime: new Date().toISOString(),
            sequenceRange: {
                start: session.startSequence,
                end: session.endSequence
            },
            durationMs: this.sessionDurationMs,
            chunkCount: session.chunksInSession,
            byteCount: session.bytesInSession,
            status: "complete"
        };
        
        if (this.onSessionFinalized) {
            try {
                this.onSessionFinalized(sessionData);
            } catch (error) {
                console.error(
                    "[UploadSessionManager] onSessionFinalized callback failed:",
                    error
                );
            }
        }
        
        // Also notify Python backend
        if (window.notifySessionFinalized) {
            Promise.resolve(window.notifySessionFinalized(sessionData))
                .catch((error) => {
                    console.warn(
                        "[UploadSessionManager] notifySessionFinalized failed:",
                        error
                    );
                });
        }
    }
    
    /**
     * Notify manager that a chunk was queued in active session.
     * Called by upload queue when chunk is enqueued.
     */
    notifyChunkQueued(chunk) {
        if (!this.activeSession) {
            return;
        }
        
        this.activeSession.chunksInSession++;
        this.activeSession.bytesInSession += chunk.data.byteLength;
        this.totalChunksInSessions++;
        this.totalBytesInSessions += chunk.data.byteLength;
        
        this._updateMetrics();
    }
    
    /**
     * Get current session info.
     * @returns {Object} Active session info
     */
    getActiveSession() {
        return this.activeSession ? { ...this.activeSession } : null;
    }
    
    /**
     * Get session history.
     * @returns {Array} Completed sessions
     */
    getSessionHistory() {
        return [...this.sessionHistory];
    }
    
    /**
     * Get elapsed time in current session.
     * @returns {number} Milliseconds
     */
    getSessionElapsedMs() {
        if (!this.activeSession) {
            return 0;
        }
        return Date.now() - this.activeSession.startTime.getTime();
    }
    
    /**
     * Get remaining time in current session.
     * @returns {number} Milliseconds
     */
    getSessionRemainingMs() {
        const elapsed = this.getSessionElapsedMs();
        const remaining = Math.max(0, this.sessionDurationMs - elapsed);
        return remaining;
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
                    "[UploadSessionManager] onMetricsUpdate failed:",
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
        const elapsed = this.getSessionElapsedMs();
        const remaining = this.getSessionRemainingMs();
        const percentComplete = (elapsed / this.sessionDurationMs) * 100;
        
        return {
            isRunning: this.isRunning,
            activeSessionId: this.activeSession ? this.activeSession.sessionId : null,
            activeSessionStartTime: this.activeSession ? this.activeSession.startTime.toISOString() : null,
            sessionElapsedMs: elapsed,
            sessionRemainingMs: remaining,
            sessionPercentComplete: percentComplete.toFixed(1) + "%",
            chunksInActiveSession: this.activeSession ? this.activeSession.chunksInSession : 0,
            bytesInActiveSession: this.activeSession ? (this.activeSession.bytesInSession / (1024 * 1024)).toFixed(2) : "0.00",
            totalSessionsCompleted: this.totalSessions,
            totalChunksAllSessions: this.totalChunksInSessions,
            totalBytesAllSessions: (this.totalBytesInSessions / (1024 * 1024)).toFixed(2),
            sessionHistoryCount: this.sessionHistory.length
        };
    }
    
    /**
     * Finalize current session (for recording stop).
     * @returns {Promise} Resolves when finalization complete
     */
    async finalizeCurrent() {
        if (!this.activeSession) {
            console.log("[UploadSessionManager] No active session to finalize");
            return;
        }
        
        // Clear rotation timer
        if (this.sessionRotationTimer) {
            clearTimeout(this.sessionRotationTimer);
            this.sessionRotationTimer = null;
        }
        
        // Mark as finalized with final sequence
        this.activeSession.endSequence = this.uploadQueue.globalSequence;
        this.activeSession.status = "finalized";
        
        console.log(
            `[UploadSessionManager] Finalizing session ${this.activeSession.sessionId}, ` +
            `duration ${this.getSessionElapsedMs()}ms, ` +
            `chunks ${this.activeSession.chunksInSession}, ` +
            `size ${(this.activeSession.bytesInSession / (1024 * 1024)).toFixed(2)}MB`
        );
        
        // Emit finalization
        this._emitSessionFinalization(this.activeSession);
        
        // Save to history
        this.sessionHistory.push(this.activeSession);
        this.totalSessions++;
        
        this.activeSession = null;
        this._updateMetrics();
    }
    
    /**
     * Stop the session manager.
     */
    stop() {
        if (this.sessionRotationTimer) {
            clearTimeout(this.sessionRotationTimer);
            this.sessionRotationTimer = null;
        }
        
        this.isRunning = false;
        console.log(
            `[UploadSessionManager] Stopped after ${this.totalSessions} sessions`
        );
    }
    
    /**
     * Get recovery info for resuming interrupted recording.
     * @returns {Object} Recovery state
     */
    getRecoveryInfo() {
        return {
            meetingId: this.meetingId,
            lastSessionId: this.activeSession ? this.activeSession.sessionId : null,
            globalSequence: this.uploadQueue.globalSequence,
            completedSessions: this.sessionHistory.map((s) => ({
                sessionId: s.sessionId,
                sequenceRange: {
                    start: s.startSequence,
                    end: s.endSequence
                },
                status: s.status
            })),
            timestamp: new Date().toISOString()
        };
    }
}


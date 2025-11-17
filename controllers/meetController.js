import { MeetingManager } from "../services/meetingManager.js";
import { extractMeetingCode } from "../services/utils/utils.js";

const manager = MeetingManager.getInstance();

/**
 * Create a new meeting and join it
 * Body: { meetingUrl, adminUser?, asGuest? }
 * Returns: { meetingId, message }
 */
const loginController = async (req, res) => {
  try {
    const { meetingUrl, adminUser, asGuest = false } = req.body;
    
    if (!meetingUrl) {
      return res.status(400).json({ error: "meetingUrl is required" });
    }

    console.log("📞 [Controller] Login request for:", meetingUrl);
    
    const { meetingId } = await manager.createMeeting(
      meetingUrl,
      adminUser || {},
      asGuest
    );

    // TODO: Return meeting ID in proper format

    res.json({
      meetingId, // Returns meeting code (e.g., "xvh-gzvz-oor")
      message: "Meeting joined successfully",
      meetingUrl,
    });
  } catch (err) {
    console.error("❌ [Controller] Failed to join meeting:", err);
    res.status(500).json({ 
      error: "Failed to join meeting",
      details: err.message 
    });
  }
};

/**
 * Leave a meeting and cleanup
 * Body: { meetingId } or { meetingUrl }
 */
const exitMeeting = async (req, res) => {
  try {
    let { meetingId, meetingUrl } = req.body;
    
    // Extract meetingId from URL if URL is provided instead
    if (!meetingId && meetingUrl) {
      try {
        meetingId = extractMeetingCode(meetingUrl);
        console.log(`📞 [Controller] Extracted meetingId from URL: ${meetingId}`);
      } catch (error) {
        return res.status(400).json({ error: "Invalid meeting URL format" });
      }
    }
    
    if (!meetingId) {
      return res.status(400).json({ error: "meetingId or meetingUrl is required" });
    }

    console.log(`🚪 [Controller] Exit meeting request for: ${meetingId}`);

    await manager.sendCommand(meetingId, "LEAVE", null, 10000);
    
    res.json({
      meetingId,
      message: "Left the meeting successfully",
    });
  } catch (err) {
    if (err.message.includes("not found")) {
      return res.status(404).json({ error: "Meeting not found" });
    }
    
    console.error("❌ [Controller] Error leaving the meeting:", err);
    res.status(500).json({ 
      error: "Failed to leave the meeting",
      details: err.message 
    });
  }
};

/**
 * Start captions for a meeting
 * Body: { meetingId } or { meetingUrl }
 */
const startCaptionsController = async (req, res) => {
  try {
    let { meetingId, meetingUrl } = req.body;
    
    if (!meetingId && meetingUrl) {
      try {
        meetingId = extractMeetingCode(meetingUrl);
      } catch (error) {
        return res.status(400).json({ error: "Invalid meeting URL format" });
      }
    }
    
    if (!meetingId) {
      return res.status(400).json({ error: "meetingId or meetingUrl is required" });
    }

    console.log(`📝 [Controller] Start captions request for: ${meetingId}`);

    await manager.sendCommand(meetingId, "START_CAPTIONS", null, 5000);
    
    res.json({
      meetingId,
      message: "Captions started",
    });
  } catch (err) {
    if (err.message.includes("not found")) {
      return res.status(404).json({ error: "Meeting not found" });
    }
    
    console.error("❌ [Controller] Error starting captions:", err);
    res.status(500).json({ 
      error: "Failed to start captions",
      details: err.message 
    });
  }
};

/**
 * Stop captions and get captured text
 * Body: { meetingId } or { meetingUrl }
 */
const stopCaptionsController = async (req, res) => {
  try {
    let { meetingId, meetingUrl } = req.body;
    
    if (!meetingId && meetingUrl) {
      try {
        meetingId = extractMeetingCode(meetingUrl);
      } catch (error) {
        return res.status(400).json({ error: "Invalid meeting URL format" });
      }
    }
    
    if (!meetingId) {
      return res.status(400).json({ error: "meetingId or meetingUrl is required" });
    }

    console.log(`📝 [Controller] Stop captions request for: ${meetingId}`);

    const result = await manager.sendCommand(
      meetingId,
      "STOP_CAPTIONS",
      null,
      5000
    );
    
    res.json({
      meetingId,
      message: "Captions stopped",
      captions: result.captions,
    });
  } catch (err) {
    if (err.message.includes("not found")) {
      return res.status(404).json({ error: "Meeting not found" });
    }
    
    console.error("❌ [Controller] Error stopping captions:", err);
    res.status(500).json({ 
      error: "Failed to stop captions",
      details: err.message 
    });
  }
};

/**
 * Start playing audio in meeting
 * Body: { meetingId } or { meetingUrl }
 */
const startAudioController = async (req, res) => {
  try {
    let { meetingId, meetingUrl } = req.body;
    
    if (!meetingId && meetingUrl) {
      try {
        meetingId = extractMeetingCode(meetingUrl);
      } catch (error) {
        return res.status(400).json({ error: "Invalid meeting URL format" });
      }
    }
    
    if (!meetingId) {
      return res.status(400).json({ error: "meetingId or meetingUrl is required" });
    }

    console.log(`🔊 [Controller] Start audio request for: ${meetingId}`);

    await manager.sendCommand(meetingId, "PLAY_AUDIO", null, 5000);
    
    res.json({
      meetingId,
      message: "Audio started",
    });
  } catch (err) {
    if (err.message.includes("not found")) {
      return res.status(404).json({ error: "Meeting not found" });
    }
    
    console.error("❌ [Controller] Error starting audio:", err);
    res.status(500).json({ 
      error: "Failed to start audio",
      details: err.message 
    });
  }
};

/**
 * Pause audio in meeting
 * Body: { meetingId } or { meetingUrl }
 */
const stopAudioController = async (req, res) => {
  try {
    let { meetingId, meetingUrl } = req.body;
    
    if (!meetingId && meetingUrl) {
      try {
        meetingId = extractMeetingCode(meetingUrl);
      } catch (error) {
        return res.status(400).json({ error: "Invalid meeting URL format" });
      }
    }
    
    if (!meetingId) {
      return res.status(400).json({ error: "meetingId or meetingUrl is required" });
    }

    console.log(`🔇 [Controller] Stop audio request for: ${meetingId}`);

    await manager.sendCommand(meetingId, "PAUSE_AUDIO", null, 5000);
    
    res.json({
      meetingId,
      message: "Audio paused",
    });
  } catch (err) {
    if (err.message.includes("not found")) {
      return res.status(404).json({ error: "Meeting not found" });
    }
    
    console.error("❌ [Controller] Error pausing audio:", err);
    res.status(500).json({ 
      error: "Failed to pause audio",
      details: err.message 
    });
  }
};

/**
 * Start audio recording for a meeting
 * Body: { meetingId } or { meetingUrl }
 */
const startRecordingController = async (req, res) => {
  try {
    let { meetingId, meetingUrl } = req.body;
    
    if (!meetingId && meetingUrl) {
      try {
        meetingId = extractMeetingCode(meetingUrl);
      } catch (error) {
        return res.status(400).json({ error: "Invalid meeting URL format" });
      }
    }
    
    if (!meetingId) {
      return res.status(400).json({ error: "meetingId or meetingUrl is required" });
    }

    console.log(`🎙️ [Controller] Start recording request for: ${meetingId}`);

    const result = await manager.sendCommand(
      meetingId,
      "START_RECORDING",
      null,
      5000
    );
    
    res.json({
      meetingId,
      message: "Audio recording started",
      ...result,
    });
  } catch (err) {
    if (err.message.includes("not found")) {
      return res.status(404).json({ error: "Meeting not found" });
    }
    
    console.error("❌ [Controller] Error starting audio recording:", err);
    res.status(500).json({ 
      error: "Failed to start audio recording",
      details: err.message 
    });
  }
};

/**
 * Stop audio recording for a meeting
 * Body: { meetingId } or { meetingUrl }
 */
const stopRecordingController = async (req, res) => {
  try {
    let { meetingId, meetingUrl } = req.body;
    
    if (!meetingId && meetingUrl) {
      try {
        meetingId = extractMeetingCode(meetingUrl);
      } catch (error) {
        return res.status(400).json({ error: "Invalid meeting URL format" });
      }
    }
    
    if (!meetingId) {
      return res.status(400).json({ error: "meetingId or meetingUrl is required" });
    }

    console.log(`⏹️ [Controller] Stop recording request for: ${meetingId}`);

    const result = await manager.sendCommand(
      meetingId,
      "STOP_RECORDING",
      null,
      5000
    );
    
    res.json({
      meetingId,
      message: "Audio recording stopped",
      duration: result.duration,
    });
  } catch (err) {
    if (err.message.includes("not found")) {
      return res.status(404).json({ error: "Meeting not found" });
    }
    
    console.error("❌ [Controller] Error stopping audio recording:", err);
    res.status(500).json({ 
      error: "Failed to stop audio recording",
      details: err.message 
    });
  }
};

/**
 * Get recording status for a meeting
 * Query: ?meetingId=xxx or ?meetingUrl=xxx
 * Body: { meetingId } or { meetingUrl }
 */
const getRecordingStatusController = async (req, res) => {
  try {
    let meetingId = req.query.meetingId || req.body.meetingId;
    let meetingUrl = req.query.meetingUrl || req.body.meetingUrl;
    
    if (!meetingId && meetingUrl) {
      try {
        meetingId = extractMeetingCode(meetingUrl);
      } catch (error) {
        return res.status(400).json({ error: "Invalid meeting URL format" });
      }
    }
    
    if (!meetingId) {
      return res.status(400).json({ error: "meetingId or meetingUrl is required" });
    }

    console.log(`📊 [Controller] Get recording status request for: ${meetingId}`);

    const status = manager.getMeetingStatus(meetingId);
    
    if (!status) {
      return res.status(404).json({ error: "Meeting not found" });
    }

    res.json({
      meetingId,
      status: status.status,
      isRecording: status.status === "recording",
      uptime: status.uptime,
    });
  } catch (err) {
    console.error("❌ [Controller] Error getting recording status:", err);
    res.status(500).json({ 
      error: "Failed to get recording status",
      details: err.message 
    });
  }
};

/**
 * Start chat scraping for a meeting
 * Body: { meetingId } or { meetingUrl }
 */
const startChatScrapingController = async (req, res) => {
  try {
    let { meetingId, meetingUrl } = req.body;
    
    if (!meetingId && meetingUrl) {
      try {
        meetingId = extractMeetingCode(meetingUrl);
      } catch (error) {
        return res.status(400).json({ error: "Invalid meeting URL format" });
      }
    }
    
    if (!meetingId) {
      return res.status(400).json({ error: "meetingId or meetingUrl is required" });
    }

    console.log(`💬 [Controller] Start chat scraping request for: ${meetingId}`);

    await manager.sendCommand(meetingId, "START_CHAT_SCRAPING", null, 5000);
    
    res.json({
      meetingId,
      message: "Chat scraping started",
    });
  } catch (err) {
    if (err.message.includes("not found")) {
      return res.status(404).json({ error: "Meeting not found" });
    }
    
    console.error("❌ [Controller] Error starting chat scraping:", err);
    res.status(500).json({ 
      error: "Failed to start chat scraping",
      details: err.message 
    });
  }
};

/**
 * Stop chat scraping and get messages
 * Body: { meetingId } or { meetingUrl }
 */
const stopChatScrapingController = async (req, res) => {
  try {
    let { meetingId, meetingUrl } = req.body;
    
    if (!meetingId && meetingUrl) {
      try {
        meetingId = extractMeetingCode(meetingUrl);
      } catch (error) {
        return res.status(400).json({ error: "Invalid meeting URL format" });
      }
    }
    
    if (!meetingId) {
      return res.status(400).json({ error: "meetingId or meetingUrl is required" });
    }

    console.log(`💬 [Controller] Stop chat scraping request for: ${meetingId}`);

    const result = await manager.sendCommand(
      meetingId,
      "STOP_CHAT_SCRAPING",
      null,
      5000
    );
    
    res.json({
      meetingId,
      message: "Chat scraping stopped",
      chatSegments: result.chatSegments,
    });
  } catch (err) {
    if (err.message.includes("not found")) {
      return res.status(404).json({ error: "Meeting not found" });
    }
    
    console.error("❌ [Controller] Error stopping chat scraping:", err);
    res.status(500).json({ 
      error: "Failed to stop chat scraping",
      details: err.message 
    });
  }
};

/**
 * Get status of a specific meeting
 * Query: ?meetingId=xxx or ?meetingUrl=xxx
 * Params: /:meetingId
 */
const getMeetingStatusController = async (req, res) => {
  try {
    let meetingId = req.params.meetingId || req.query.meetingId;
    let meetingUrl = req.query.meetingUrl;
    
    if (!meetingId && meetingUrl) {
      try {
        meetingId = extractMeetingCode(meetingUrl);
      } catch (error) {
        return res.status(400).json({ error: "Invalid meeting URL format" });
      }
    }
    
    if (!meetingId) {
      return res.status(400).json({ error: "meetingId or meetingUrl is required" });
    }

    console.log(`📊 [Controller] Get meeting status request for: ${meetingId}`);

    const status = manager.getMeetingStatus(meetingId);
    
    if (!status) {
      return res.status(404).json({ error: "Meeting not found" });
    }

    res.json(status);
  } catch (err) {
    console.error("❌ [Controller] Error getting meeting status:", err);
    res.status(500).json({ 
      error: "Failed to get meeting status",
      details: err.message 
    });
  }
};

/**
 * Get all active meetings
 */
const getAllMeetingsController = async (req, res) => {
  try {
    console.log(`📊 [Controller] Get all meetings request`);
    
    const meetings = manager.getAllMeetings();
    
    res.json({
      count: meetings.length,
      meetings,
    });
  } catch (err) {
    console.error("❌ [Controller] Error getting all meetings:", err);
    res.status(500).json({ 
      error: "Failed to get meetings",
      details: err.message 
    });
  }
};

/**
 * Add a recipient to meeting's email list
 * Body: { meetingId, email } or { meetingUrl, email }
 */
const addRecipientController = async (req, res) => {
  try {
    let { meetingId, meetingUrl, email } = req.body;
    
    if (!meetingId && meetingUrl) {
      try {
        meetingId = extractMeetingCode(meetingUrl);
      } catch (error) {
        return res.status(400).json({ error: "Invalid meeting URL format" });
      }
    }
    
    if (!meetingId || !email) {
      return res.status(400).json({ 
        error: "meetingId (or meetingUrl) and email are required" 
      });
    }

    console.log(`📧 [Controller] Add recipient request for meeting ${meetingId}: ${email}`);

    const result = await manager.sendCommand(
      meetingId,
      "ADD_RECIPIENT",
      { email },
      5000
    );
    
    res.json({
      meetingId,
      message: "Recipient added",
      recipients: result.recipients,
    });
  } catch (err) {
    if (err.message.includes("not found")) {
      return res.status(404).json({ error: "Meeting not found" });
    }
    
    console.error("❌ [Controller] Error adding recipient:", err);
    res.status(500).json({ 
      error: "Failed to add recipient",
      details: err.message 
    });
  }
};

/**
 * Remove a recipient from meeting's email list
 * Body: { meetingId, email } or { meetingUrl, email }
 */
const removeRecipientController = async (req, res) => {
  try {
    let { meetingId, meetingUrl, email } = req.body;
    
    if (!meetingId && meetingUrl) {
      try {
        meetingId = extractMeetingCode(meetingUrl);
      } catch (error) {
        return res.status(400).json({ error: "Invalid meeting URL format" });
      }
    }
    
    if (!meetingId || !email) {
      return res.status(400).json({ 
        error: "meetingId (or meetingUrl) and email are required" 
      });
    }

    console.log(`📧 [Controller] Remove recipient request for meeting ${meetingId}: ${email}`);

    const result = await manager.sendCommand(
      meetingId,
      "REMOVE_RECIPIENT",
      { email },
      5000
    );
    
    res.json({
      meetingId,
      message: "Recipient removed",
      recipients: result.recipients,
    });
  } catch (err) {
    if (err.message.includes("not found")) {
      return res.status(404).json({ error: "Meeting not found" });
    }
    
    console.error("❌ [Controller] Error removing recipient:", err);
    res.status(500).json({ 
      error: "Failed to remove recipient",
      details: err.message 
    });
  }
};

/**
 * Get all recipients for a meeting
 * Query: ?meetingId=xxx or ?meetingUrl=xxx
 * Body: { meetingId } or { meetingUrl }
 */
const getRecipientsController = async (req, res) => {
  try {
    let meetingId = req.query.meetingId || req.body.meetingId;
    let meetingUrl = req.query.meetingUrl || req.body.meetingUrl;
    
    if (!meetingId && meetingUrl) {
      try {
        meetingId = extractMeetingCode(meetingUrl);
      } catch (error) {
        return res.status(400).json({ error: "Invalid meeting URL format" });
      }
    }
    
    if (!meetingId) {
      return res.status(400).json({ error: "meetingId or meetingUrl is required" });
    }

    console.log(`📧 [Controller] Get recipients request for: ${meetingId}`);

    const result = await manager.sendCommand(
      meetingId,
      "GET_RECIPIENTS",
      null,
      5000
    );
    
    res.json({
      meetingId,
      recipients: result.recipients,
    });
  } catch (err) {
    if (err.message.includes("not found")) {
      return res.status(404).json({ error: "Meeting not found" });
    }
    
    console.error("❌ [Controller] Error getting recipients:", err);
    res.status(500).json({ 
      error: "Failed to get recipients",
      details: err.message 
    });
  }
};

export {
  loginController,
  exitMeeting,
  startCaptionsController,
  stopCaptionsController,
  startAudioController,
  stopAudioController,
  startRecordingController,
  stopRecordingController,
  getRecordingStatusController,
  startChatScrapingController,
  stopChatScrapingController,
  getMeetingStatusController,
  getAllMeetingsController,
  addRecipientController,
  removeRecipientController,
  getRecipientsController,
};
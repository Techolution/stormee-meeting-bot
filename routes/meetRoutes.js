import express from "express";
import {
  loginController,
  startAudioController,
  startCaptionsController,
  stopAudioController,
  stopCaptionsController,
  startRecordingController,
  stopRecordingController,
  getRecordingStatusController,
  startChatScrapingController,
  stopChatScrapingController,
  getAllMeetingsController,
  exitMeeting,
} from "../controllers/meetController.js";

import {
    addRecipientController,
    removeRecipientController,
    getRecipientsController
} from "../controllers/recipientController.js";

const router = express.Router();

// Health check route
const checkingHealth = (req, res) => {
  res.status(200).json({ status: "OK", message: "Service is running" });
};

// Recipient routes
router.get("/recipient/fetch", getRecipientsController);
router.post("/recipient/add", addRecipientController);
router.delete("/recipient/remove", removeRecipientController);

// Existing API routes for Google Meet functionality
router.post("/start", startCaptionsController);
router.post("/stop", stopCaptionsController);
router.get("/health", checkingHealth);
router.post("/audio", startAudioController);
router.post("/signin", loginController);
router.post("/pauseaudio", stopAudioController);
router.get("/meetings", getAllMeetingsController);

// New API routes for audio recording functionality
router.post("/record/start", startRecordingController);
router.post("/record/stop", stopRecordingController);
router.get("/record/status", getRecordingStatusController);
router.post('/chat/start',startChatScrapingController);
router.get('/chat/stop',stopChatScrapingController);
router.post('/exit',exitMeeting);

export default router;

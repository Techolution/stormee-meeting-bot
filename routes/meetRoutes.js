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
} from "../controllers/meetController.js";

const router = express.Router();

// Health check route
const checkingHealth = (req, res) => {
  res.status(200).json({ status: "OK", message: "Service is running" });
};

// Existing API routes for Google Meet functionality
router.post("/start", startCaptionsController);
router.post("/stop", stopCaptionsController);
router.get("/health", checkingHealth);
router.post("/audio", startAudioController);
router.post("/signin", loginController);
router.post("/pauseaudio", stopAudioController);

// New API routes for audio recording functionality
router.post("/record/start", startRecordingController);
router.post("/record/stop", stopRecordingController);
router.get("/record/status", getRecordingStatusController);
router.post('/chat/start',startChatScrapingController);
router.get('/chat/stop',stopChatScrapingController);

export default router;

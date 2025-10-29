import express from "express";
import {
  loginController,
  startAudioController,
  startCaptionsController,
  stopAudioController,
  stopCaptionsController,
} from "../controllers/meetController.js";

const router = express.Router();

// Health check route
const checkingHealth = (req, res) => {
  res.status(200).json({ status: "OK", message: "Service is running" });
};

// API routes for Chrome Extension
router.post("/start-meeting", startCaptionsController);
router.post("/stop-meeting", stopCaptionsController);

// Existing API routes (preserved for backward compatibility)
router.post("/meet/start", startCaptionsController);
router.post("/meet/stop", stopCaptionsController);
router.get("/meet/health", checkingHealth);
router.post("/meet/audio", startAudioController);
router.post("/meet/signin", loginController);
router.post("/meet/pauseaudio", stopAudioController);

export default router;

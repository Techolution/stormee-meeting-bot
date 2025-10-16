const express = require("express");
const router = express.Router();
const {
  startMeet,
  stopMeet,
  playAudio,
  pauseAudio,
  startCaptions,
  stopCaptions,
  healthCheck,
  speakController,
} = require("../controllers/meetController");

// Health check endpoint
router.get("/health", healthCheck);

// Meeting management endpoints
router.post("/start", startMeet);
router.post("/stop", stopMeet);

// Audio control endpoints
router.post("/audio", playAudio);
router.post("/pauseaudio", pauseAudio);

// Caption control endpoints
router.post("/captions/start", startCaptions);
router.post("/captions/stop", stopCaptions);

// Voice synthesis endpoint
router.post("/speak", speakController);

module.exports = router;

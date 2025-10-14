import express from "express";
import { loginController, speakController, startAudioController, startCaptionsController, stopAudioController, stopCaptionsController } from "../controllers/meetController.js";

const router = express.Router();

// Health check route
const checkingHealth = (req, res) => {
    res.status(200).json({ status: "OK", message: "Service is running" });
}

// API routes
router.post("/start", startCaptionsController);
router.post("/stop", stopCaptionsController);
router.get('/health', checkingHealth); // Fixed typo
router.post('/playaudio', startAudioController);
router.post('/signin',loginController);
router.post('/pauseaudio',stopAudioController);
router.post('/speak',speakController);

export default router;

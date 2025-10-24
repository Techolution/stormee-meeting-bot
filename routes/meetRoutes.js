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

/**
 * @swagger
 * /health:
 *   get:
 *     summary: Health check
 *     tags: [Utility]
 *     responses:
 *       200:
 *         description: Service is running
 *         content:
 *           application/json:
 *             schema:
 *               type: object
 *               properties:
 *                 status:
 *                   type: string
 *                   example: OK
 *                 message:
 *                   type: string
 *                   example: Service is running
 */
router.get("/health", checkingHealth);

/**
 * @swagger
 * /signin:
 *   post:
 *     summary: Join a Google Meet meeting
 *     tags: [Meeting Control]
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - meetingUrl
 *             properties:
 *               meetingUrl:
 *                 type: string
 *                 example: https://meet.google.com/abc-xyz-def
 *     responses:
 *       200:
 *         description: Meeting joined successfully
 *         content:
 *           application/json:
 *             schema:
 *               type: object
 *               properties:
 *                 message:
 *                   type: string
 *                   example: Meeting joined
 *       400:
 *         description: Invalid input
 *       500:
 *         description: Failed to join meeting
 */
router.post("/signin", loginController);

/**
 * @swagger
 * /start:
 *   post:
 *     summary: Start scraping captions/transcript
 *     tags: [Captions]
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - meetingUrl
 *             properties:
 *               meetingUrl:
 *                 type: string
 *                 example: https://meet.google.com/abc-xyz-def
 *     responses:
 *       200:
 *         description: Caption scraping started
 *         content:
 *           application/json:
 *             schema:
 *               type: object
 *               properties:
 *                 message:
 *                   type: string
 *                   example: Captions started
 *       400:
 *         description: Invalid input
 *       500:
 *         description: Failed to start captions
 */
router.post("/start", startCaptionsController);

/**
 * @swagger
 * /stop:
 *   post:
 *     summary: Stop captions scraping and return the full transcript
 *     tags: [Captions]
 *     responses:
 *       200:
 *         description: Captions stopped and transcript returned
 *         content:
 *           application/json:
 *             schema:
 *               type: object
 *               properties:
 *                 message:
 *                   type: string
 *                   example: Captions stopped
 *                 captions:
 *                   type: array
 *                   items:
 *                     type: object
 *                     properties:
 *                       text:
 *                         type: string
 *                         example: This is a spoken sentence.
 *                       timestamp:
 *                         type: string
 *                         format: date-time
 *                         example: 2023-10-21T10:00:00.000Z
 *       500:
 *         description: Failed to stop captions
 */
router.post("/stop", stopCaptionsController);

/**
 * @swagger
 * /audio:
 *   post:
 *     summary: Turn on the bot's microphone
 *     tags: [Meeting Control]
 *     responses:
 *       200:
 *         description: Audio enabled
 *         content:
 *           application/json:
 *             schema:
 *               type: object
 *               properties:
 *                 message:
 *                   type: string
 *                   example: Audio played
 *       400:
 *         description: No active meeting
 *       500:
 *         description: Failed to enable audio
 */
router.post("/audio", startAudioController);

/**
 * @swagger
 * /pauseaudio:
 *   post:
 *     summary: Mute the bot's microphone
 *     tags: [Meeting Control]
 *     responses:
 *       200:
 *         description: Audio muted
 *         content:
 *           application/json:
 *             schema:
 *               type: object
 *               properties:
 *                 message:
 *                   type: string
 *                   example: Audio paused
 *       500:
 *         description: Failed to pause audio
 */
router.post("/pauseaudio", stopAudioController);

/**
 * @swagger
 * /record/start:
 *   post:
 *     summary: Start recording and streaming the full meeting audio
 *     tags: [Recording]
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - meetingId
 *             properties:
 *               meetingId:
 *                 type: string
 *                 example: GMeet-12345
 *     responses:
 *       200:
 *         description: Audio recording started
 *         content:
 *           application/json:
 *             schema:
 *               type: object
 *               properties:
 *                 message:
 *                   type: string
 *                   example: Audio recording started
 *                 meetingId:
 *                   type: string
 *                   example: GMeet-12345
 *       400:
 *         description: Invalid input
 *       500:
 *         description: Failed to start audio recording
 */
router.post("/record/start", startRecordingController);

/**
 * @swagger
 * /record/stop:
 *   post:
 *     summary: Stop recording, save, and convert the audio file
 *     tags: [Recording]
 *     responses:
 *       200:
 *         description: Audio recording stopped and file saved/converted
 *         content:
 *           application/json:
 *             schema:
 *               type: object
 *               properties:
 *                 message:
 *                   type: string
 *                   example: Audio recording stopped
 *       500:
 *         description: Failed to stop audio recording
 */
router.post("/record/stop", stopRecordingController);

/**
 * @swagger
 * /record/status:
 *   get:
 *     summary: Get the current audio recording status (Placeholder)
 *     tags: [Recording]
 *     responses:
 *       200:
 *         description: Returns the current recording status
 *         content:
 *           application/json:
 *             schema:
 *               type: object
 *               properties:
 *                 message:
 *                   type: string
 *                   example: Recording status feature not yet implemented
 *                 status:
 *                   type: string
 *                   example: unknown
 */
router.get("/record/status", getRecordingStatusController);

/**
 * @swagger
 * /chat/start:
 *   post:
 *     summary: Start scraping and monitoring the meeting chat
 *     tags: [Chat]
 *     responses:
 *       200:
 *         description: Chat scraping started
 *         content:
 *           application/json:
 *             schema:
 *               type: object
 *               properties:
 *                 message:
 *                   type: string
 *                   example: Chat scraping started
 *       500:
 *         description: Failed to start chat scraping
 */
router.post('/chat/start', startChatScrapingController);

/**
 * @swagger
 * /chat/stop:
 *   get:
 *     summary: Stop chat scraping and return collected chat segments
 *     tags: [Chat]
 *     responses:
 *       200:
 *         description: Chat scraping stopped
 *         content:
 *           application/json:
 *             schema:
 *               type: object
 *               properties:
 *                 message:
 *                   type: string
 *                   example: Chat scraping stopped
 *                 chatSegments:
 *                   type: array
 *                   items:
 *                     type: object
 *                     properties:
 *                       sender:
 *                         type: string
 *                         example: John Doe
 *                       text:
 *                         type: string
 *                         example: Great presentation!
 *                       timestamp:
 *                         type: string
 *                         format: date-time
 *                         example: 2023-10-21T10:05:00.000Z
 *       500:
 *         description: Failed to stop chat scraping
 */
router.get('/chat/stop', stopChatScrapingController);

export default router;

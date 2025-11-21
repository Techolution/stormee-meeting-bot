import express from "express";
import dotenv from "dotenv";
import meetRoutes from "./routes/meetRoutes.js";
import cors from "cors";
import { createServer } from "http";
import { Server } from "socket.io";
import './services/jobs/authCleaner.js';

dotenv.config();

const app = express();

// Middleware setup
app.use(express.json());
app.use(cors());

// API routes
app.use("/meeting_recorder_stormee", meetRoutes);

// Create HTTP server from Express app
const httpServer = createServer(app);

// Initialize Socket.IO server with CORS configuration
const io = new Server(httpServer, {
  cors: {
    origin: "*", // Allow connections from any origin - adjust for production
    methods: ["GET", "POST"],
  },
});

// WebSocket connection handler
io.on("connection", (socket) => {
  console.log("🔌 A client connected via WebSocket:", socket.id);

  // Handle incoming audio chunks from the bot
  socket.on("audioChunk", (data) => {
    // console.log(
    //   `🎵 Received audio chunk from meeting ${data.meetingId}, chunk ID: ${data.chunkId}`
    // );
    console.log(`📅 Timestamp: ${data.timestamp}`);
    console.log(
      `📊 Audio data size: ${
        data.audioBlob ? data.audioBlob.length : "N/A"
      } bytes`
    );

    // TODO: Process the audio chunk (save to disk, forward to analysis service, etc.)
    // Example implementations:
    // - saveAudioChunk(data.meetingId, data.chunkId, data.timestamp, data.audioBlob);
    // - forwardToTranscriptionService(data);
    // - storeInDatabase(data);
  });

  // Handle client disconnection
  socket.on("disconnect", (reason) => {
    console.log("🔌 Client disconnected:", socket.id, "Reason:", reason);
  });

  // Handle connection errors
  socket.on("error", (error) => {
    console.error("❌ WebSocket error for client", socket.id, ":", error);
  });
});

const PORT = process.env.PORT ?? 8080;
const BACKEND_URL= process.env.BACKEND_URL ?? `http://localhost:${PORT}`;

// Start the combined HTTP and WebSocket server
httpServer.listen(PORT, () => {
  console.log(`🚀 Express server running on port ${PORT}`);
  console.log(`🔌 WebSocket server running on port ${PORT}`);
  console.log(
    `📋 API endpoints available at ${BACKEND_URL}/meeting_recorder_stormee`
  );
});

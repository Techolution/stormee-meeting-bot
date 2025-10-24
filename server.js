import express from "express";
import dotenv from "dotenv";
import meetRoutes from "./routes/meetRoutes.js";
import cors from "cors";
import { createServer } from "http";
import { Server } from "socket.io";
import swaggerJSDoc from "swagger-jsdoc";
import swaggerUi from "swagger-ui-express";


dotenv.config();

const app = express();

// Middleware setup
const swaggerOptions = {
  definition: {
    openapi: "3.0.0",
    info: {
      title: "Meet API",
      version: "1.0.0",
      description: "API documentation for the Meet service",
    },
    servers: [
      {
        url: `http://localhost:${process.env.PORT || 5000}/api/meet`,
      },
    ],
  },
  apis: ["./routes/*.js"],
};

const swaggerDocs = swaggerJSDoc(swaggerOptions);
app.use("/docs", swaggerUi.serve, swaggerUi.setup(swaggerDocs));

app.use(express.json());
app.use(cors());

// API routes
app.use("/api/meet", meetRoutes);

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
    console.log(
      `🎵 Received audio chunk from meeting ${data.meetingId}, chunk ID: ${data.chunkId}`
    );
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
  // Handle connection errors
  socket.on("error", (error) => {
    console.error("❌ WebSocket error for client", socket.id, ":", error);
  });

}); // end io.on("connection")


app.get('/openapi.json', (req, res) => {
    res.setHeader('Content-Type', 'application/json');
    res.send(swaggerDocs);
  });

app.get("/", (req, res) => {
  res.send("API is running...");
});
const PORT = process.env.PORT || 5000;

// Start the combined HTTP and WebSocket server
httpServer.listen(PORT, () => {
  console.log(`🚀 Express server running on port ${PORT}`);
  console.log(`🔌 WebSocket server running on port ${PORT}`);
  console.log(
    `📋 API endpoints available at http://localhost:${PORT}/api/meet`
  );
});

import express from "express";
import dotenv from "dotenv";
import meetRoutes from "./routes/meetRoutes.js";
import cors from "cors";

dotenv.config();

const app = express();
app.use(express.json());
app.use(cors());

// New API Key Authentication Middleware
app.use((req, res, next) => {
  const apiKey = req.headers["x-api-key"];
  // Replace 'YOUR_SECRET_API_KEY' with a secure environment variable
  if (!apiKey || apiKey !== process.env.API_KEY) {
    return res
      .status(403)
      .json({ status: "error", message: "Forbidden: Invalid API Key" });
  }
  next();
});

app.use("/api", meetRoutes); // Changed base path to /api to accommodate new routes

const PORT = process.env.PORT || 5000;
app.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
});

import { startCaptions, stopCaptions } from "../services/meetBot.js";

let currentMeetingUrl = null;

const startCaptionsController = async (req, res) => {
  const { meetingUrl } = req.body;
  if (!meetingUrl) return res.status(400).json({ error: "meetingUrl is required" });

  currentMeetingUrl = meetingUrl;
  startCaptions(meetingUrl)
    .then(() => console.log("Captions started"))
    .catch((err) => console.error(err));

  res.json({ message: "Captions started" });
};

const stopCaptionsController = async (req, res) => {
  try {
    const captions = await stopCaptions();
    res.json({ message: "Captions stopped", captions });
  } catch (err) {
    res.status(500).json({ error: "Failed to stop captions" });
  }
};

export { startCaptionsController, stopCaptionsController };

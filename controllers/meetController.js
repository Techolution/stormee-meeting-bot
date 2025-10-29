import {
  joinMeeting,
  pauseAudio,
  playAudio,
  startCaptions,
  stopCaptions,
} from "../services/meetBot.js";

let currentMeetingUrl = null;

const startCaptionsController = async (req, res) => {
  const { meetingUrl } = req.body;
  if (!meetingUrl) {
    return res
      .status(400)
      .json({ status: "error", message: "meetingUrl is required" });
  }

  currentMeetingUrl = meetingUrl;
  try {
    await startCaptions(meetingUrl);
    console.log("Captions started");
    res.status(200).json({ status: "success", message: "Captions started" });
  } catch (err) {
    console.error(err);
    res
      .status(500)
      .json({ status: "error", message: "Failed to start captions" });
  }
};

const stopCaptionsController = async (req, res) => {
  try {
    const captions = await stopCaptions();
    res
      .status(200)
      .json({ status: "success", message: "Captions stopped", captions });
  } catch (err) {
    console.error(err);
    res
      .status(500)
      .json({ status: "error", message: "Failed to stop captions" });
  }
};

const loginController = async (req, res) => {
  try {
    const { meetingUrl } = req.body;
    if (!meetingUrl) {
      return res
        .status(400)
        .json({ status: "error", message: "meetingUrl is required" });
    }

    currentMeetingUrl = meetingUrl;
    await joinMeeting(meetingUrl);
    console.log("Joined meeting");
    res.status(200).json({ status: "success", message: "Meeting joined" });
  } catch (err) {
    console.error(err);
    res
      .status(500)
      .json({ status: "error", message: "Failed to join meeting" });
  }
};

const startAudioController = async (req, res) => {
  try {
    // This path should ideally be configurable and not hardcoded
    await playAudio(
      "/Users/deepleshgupta/Desktop/bot-poc/file_example_WAV_1MG.wav"
    );
    res.status(200).json({ status: "success", message: "Audio played" });
  } catch (err) {
    console.error(err);
    res.status(500).json({ status: "error", message: "Failed to play audio" });
  }
};

const stopAudioController = async (req, res) => {
  try {
    await pauseAudio();
    res.status(200).json({ status: "success", message: "Audio paused" });
  } catch (err) {
    console.error(err);
    res.status(500).json({ status: "error", message: "Failed to pause audio" });
  }
};

export {
  startCaptionsController,
  stopCaptionsController,
  startAudioController,
  loginController,
  stopAudioController,
};

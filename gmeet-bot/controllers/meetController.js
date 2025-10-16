const meetBot = require("../services/meetBot");

const startMeet = async (req, res) => {
  const { meetingUrl } = req.body;

  if (
    !meetingUrl ||
    typeof meetingUrl !== "string" ||
    meetingUrl.trim() === ""
  ) {
    return res
      .status(400)
      .send({
        message: "Meeting URL is required and must be a non-empty string.",
      });
  }

  try {
    if (!meetBot.isInitialized) {
      await meetBot.launchBrowser();
      await meetBot.loadAuthCookies();
    }

    await meetBot.joinMeeting(meetingUrl);
    res.status(200).send({ message: "Successfully joined the meeting." });
  } catch (error) {
    console.error("Error in startMeet:", error);
    res
      .status(500)
      .send({ message: "Failed to start meeting.", error: error.message });
  }
};

const stopMeet = async (req, res) => {
  try {
    await meetBot.leaveMeeting();
    await meetBot.closeBrowser();
    res
      .status(200)
      .send({ message: "Successfully left the meeting and closed browser." });
  } catch (error) {
    console.error("Error in stopMeet:", error);
    res
      .status(500)
      .send({ message: "Failed to stop meeting.", error: error.message });
  }
};

const playAudio = async (req, res) => {
  try {
    await meetBot.playAudio();
    res.status(200).send({ message: "Audio enabled successfully." });
  } catch (error) {
    console.error("Error in playAudio:", error);
    res
      .status(500)
      .send({ message: "Failed to enable audio.", error: error.message });
  }
};

const pauseAudio = async (req, res) => {
  try {
    await meetBot.pauseAudio();
    res.status(200).send({ message: "Audio disabled successfully." });
  } catch (error) {
    console.error("Error in pauseAudio:", error);
    res
      .status(500)
      .send({ message: "Failed to disable audio.", error: error.message });
  }
};

const startCaptions = async (req, res) => {
  try {
    await meetBot.startCaptions();
    res.status(200).send({ message: "Captions started successfully." });
  } catch (error) {
    console.error("Error in startCaptions:", error);
    res
      .status(500)
      .send({ message: "Failed to start captions.", error: error.message });
  }
};

const stopCaptions = async (req, res) => {
  try {
    await meetBot.stopCaptions();
    res.status(200).send({ message: "Captions stopped successfully." });
  } catch (error) {
    console.error("Error in stopCaptions:", error);
    res
      .status(500)
      .send({ message: "Failed to stop captions.", error: error.message });
  }
};

const healthCheck = async (req, res) => {
  try {
    const status = await meetBot.getStatus();
    res.status(200).send({
      message: "Service is running.",
      status: status,
    });
  } catch (error) {
    console.error("Error in healthCheck:", error);
    res
      .status(500)
      .send({ message: "Health check failed.", error: error.message });
  }
};

const speakController = async (req, res) => {
  const { text } = req.body;

  if (!text || typeof text !== "string" || text.trim() === "") {
    return res
      .status(400)
      .send({ message: "Text is required and must be a non-empty string." });
  }

  try {
    await meetBot.speak(text);
    res
      .status(200)
      .send({ message: "Speech synthesis initiated successfully." });
  } catch (error) {
    console.error("Error in speakController:", error);
    res
      .status(500)
      .send({ message: "Failed to synthesize speech.", error: error.message });
  }
};

module.exports = {
  startMeet,
  stopMeet,
  playAudio,
  pauseAudio,
  startCaptions,
  stopCaptions,
  healthCheck,
  speakController,
};

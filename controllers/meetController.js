import {
    joinMeeting,
    pauseAudio,
    playAudio,
    startCaptions,
    stopCaptions,
    startAudioRecording,
    stopAudioRecording,
    stopChatScraping,
    startChatScraping,
  } from "../services/meetBot.js";
  
  let currentMeetingUrl = null;
  
  const startCaptionsController = async (req, res) => {
    const { meetingUrl } = req.body;
    if (!meetingUrl)
      return res.status(400).json({ error: "meetingUrl is required" });
  
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
  
  const loginController = async (req, res) => {
    try {
      const { meetingUrl } = req.body;
      if (!meetingUrl)
        return res.status(400).json({ error: "meetingUrl is required" });
  
      currentMeetingUrl = meetingUrl;
      joinMeeting(meetingUrl)
        .then(() => console.log("Joined meeting"))
        .catch((err) => console.error(err));
      res.json({ message: "Meeting joined" });
    } catch (err) {
      res.status(500).json({ error: "Failed to join meeting" });
    }
  };
  
  const startAudioController = async (req, res) => {
    try {
      if (!currentMeetingUrl) {
        return res
          .status(400)
          .json({ error: "No active meeting. Join a meeting first." });
      }
  
      await playAudio(currentMeetingUrl);
      res.json({ message: "Audio played" });
    } catch (err) {
      res.status(500).json({ error: "Failed to play audio" });
    }
  };
  
  const stopAudioController = async (req, res) => {
    try {
      await pauseAudio();
      res.json({ message: "Audio paused" });
    } catch (err) {
      res.status(500).json({ error: "Failed to pause audio" });
    }
  };
  
  // New controllers for audio recording
  const startRecordingController = async (req, res) => {
    const { meetingId } = req.body;
    if (!meetingId)
      return res.status(400).json({ error: "meetingId is required" });
  
    try {
      await startAudioRecording(meetingId);
      res.json({ message: "Audio recording started", meetingId });
    } catch (err) {
      console.error("Error starting audio recording:", err);
      res.status(500).json({ error: "Failed to start audio recording" });
    }
  };
  
  const stopRecordingController = async (req, res) => {
    try {
      await stopAudioRecording();
      res.json({ message: "Audio recording stopped" });
    } catch (err) {
      console.error("Error stopping audio recording:", err);
      res.status(500).json({ error: "Failed to stop audio recording" });
    }
  };
  
  // Placeholder controller for future recording status functionality
  const getRecordingStatusController = async (req, res) => {
    // TODO: Implement logic to return current recording status from meetBot.js
    res.json({
      message: "Recording status feature not yet implemented",
      status: "unknown",
    });
  };
  const startChatScrapingController=async(req,res)=>{
    try{
        
        await startChatScraping();
        res.json({
            message:"Chat scraping started"
        })

    }
    catch(err){
        console.error("Error starting chat scraping:",err);
        res.status(500).json({error:"Failed to start chat scraping"});
    }
  }
  const stopChatScrapingController=async(req,res)=>{
    try{
        await stopChatScraping();
        res.json({
            message:"Chat scraping stopped"
        })

    }
    catch(err){
        console.error("Error stopping chat scraping:",err);
        res.status(500).json({error:"Failed to stop chat scraping"});
    }
  }
  
  export {
    startCaptionsController,
    stopCaptionsController,
    startAudioController,
    loginController,
    stopAudioController,
    startRecordingController,
    stopRecordingController,
    getRecordingStatusController,
    startChatScrapingController,
    stopChatScrapingController
  };
  
import { joinMeeting, pauseAudio, playAudio, speak, startCaptions, stopCaptions } from "../services/meetBot.js";

let currentMeetingUrl = null;

const startCaptionsController = async (req, res) => {
  
  startCaptions()
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
const loginController=async(req,res)=>{
    try {
        const { meetingUrl } = req.body;
        if (!meetingUrl) return res.status(400).json({ error: "meetingUrl is required" });
      
        currentMeetingUrl = meetingUrl;
        joinMeeting(meetingUrl)
          .then(() => console.log("Joined meeting"))
          .catch((err) => console.error(err));
          res.json({message:"Meeting joined"})
    }
    catch(err){
        res.status(500).json({ error: "Failed to join meeting" });
    }
}
const startAudioController=async(req,res)=>{
    try{
        await playAudio('/Users/deepanshgupta/Desktop/bot-poc/file_example_WAV_1MG.wav');

        res.json({message:"Audio played"});
    }
    catch(err){
        res.status(500).json({error:"Failed to play audio"});
    }
}
const stopAudioController=async(req,res)=>{
    try{
        await pauseAudio();
        res.json({message:"Audio paused"});

    }
    catch(err){
        res.status(500).json({error:"Failed to pause audio"});
    }
}
const speakController=async(req,res)=>{
    try{
        await speak(currentMeetingUrl,'/Users/deepanshgupta/Desktop/bot-poc/file_example_WAV_1MG.wav',8000);
        res.json({message:"Audio played"});
    }
    catch(err){
        res.status(500).json({error:"Failed to play audio"});
    }
}

export { startCaptionsController, stopCaptionsController ,startAudioController,loginController,stopAudioController,speakController};

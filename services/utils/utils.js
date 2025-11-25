import {  sendEmail } from "../integrations/externalAPIS.js";
import generateMeetingMinutesEmailInMOMScreen from "../sendEmail.js";
function processMeetingData(topicsData) {
    const meetingData = { ...topicsData }; // shallow clone to avoid direct mutation
  
    const minuteObjects =
      meetingData?.diarization_json?.transcription?.unique_mom?.[0]?.minute_objects;
  
    if (Array.isArray(minuteObjects)) {
      const sortedObjects = minuteObjects
        .map((item) => ({ ...item })) // clone items to avoid side effects
        .sort((a, b) => {
          if (b.importance_score !== a.importance_score) {
            return b.importance_score - a.importance_score;
          }
          return b.relevancy_score - a.relevancy_score;
        });
  
      // store the sorted result back into the meetingData object
     return sortedObjects;
    }
  }
  
  const createArtifactAndSendEmail = async (artifactData,projectId, recipients=[]) => {
    const artifactJson=artifactData.artifact_upload_result.artifact_data.artifactData;
    // console.log("artifactJson",artifactJson);
    if(!artifactJson)return;
    const tasks=artifactJson.itemListJson.formatted_action_items;
    const description= artifactJson.transcriptJson.diarization_json.audioDescription;
    const audioFileName=artifactJson.transcriptJson.diarization_json.audio_filename;
    const meetingData=processMeetingData(artifactJson.transcriptJson);
    console.log("tasks:", tasks.length);
    console.log("description:", description);
    console.log("audioFileName:", audioFileName);
    console.log("meetingData:", meetingData);
    if(description&&audioFileName&&tasks.length>0&&meetingData){
      console.log('all data present');
      const emailBody = await generateMeetingMinutesEmailInMOMScreen(
        meetingData,
        tasks,
        artifactData.artifact_id,
        description,
        audioFileName,
        projectId,
        ""
      );
      console.log("emailBOdy",emailBody)
      if(emailBody){
        try{
        console.log("sending email to recipients:",recipients);
        const emailPromises = recipients.map((email) =>
            sendEmail({
              to_email: email,
              subject: `Meeting Minutes for ${audioFileName}`,
              body: emailBody
            })
          );

          const responses = await Promise.allSettled(emailPromises);

          responses.forEach((result, index) => {
            if (result.status === "fulfilled") {
              console.log(`Email sent successfully to recipient #${index + 1}`);
            } else {
              console.error(`Failed to send email to recipient #${index + 1}:`, result.reason);
            }
          });
    // const response=await sendEmail({to_email:process.env.USER_EMAIL,subject:`Meeting Minutes for ${audioFileName}`,body:emailBody});
    
    // console.log(responses);
    }
    catch(error){
        console.error("error in sending email",error);
    }}
}
}
 const parseAudioContent = async({audioDescription}) => {
    console.log("Parsing audio description:", audioDescription);
    const descriptionMatch = audioDescription.match(/<DESCRIPTION>([\s\S]*?)<\/DESCRIPTION>/);
    const description = descriptionMatch ? descriptionMatch[1].trim() : "";
    
    const keyTakeawaysMatch = audioDescription.match(/<KEYTAKEAWAYS>([\s\S]*?)<\/KEYTAKEAWAYS>/);
    const keyTakeawaysText = keyTakeawaysMatch ? keyTakeawaysMatch[1].trim() : "";
  
    const keyTakeaways=[]
    const lines = keyTakeawaysText.split('\n');
    
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].trim();
      if (line && /^\d+\./.test(line)) {
        // Extract the content (everything after the number and period)
        const content = line.replace(/^\d+\.\s+/, '').trim();
        if (content) {
          keyTakeaways.push({
            id: keyTakeaways.length,
            content
          });
        }
      }
    }
    return { description, keyTakeaways };
  };

function extractMeetingCode(meetingUrl) {
  if (!meetingUrl || typeof meetingUrl !== 'string') {
    throw new Error('Invalid meeting URL: must be a non-empty string');
  }

  // Remove whitespace
  const trimmed = meetingUrl.trim();

  // Pattern: meet.google.com/CODE (with optional query params)
  const fullUrlMatch = trimmed.match(/meet\.google\.com\/([a-z0-9-]+)(?:\?|$)/i);
  
  if (fullUrlMatch) {
    return fullUrlMatch[1];
  }

  // If it's already just the code (e.g., "abc-defg-hij" or "abcdefghij")
  const codePattern = /^[a-z0-9-]+$/i;
  if (codePattern.test(trimmed)) {
    return trimmed;
  }

  throw new Error(`Invalid Google Meet URL format: ${meetingUrl}`);
}

export { createArtifactAndSendEmail, parseAudioContent, extractMeetingCode};
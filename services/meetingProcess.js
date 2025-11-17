// // It receives commands from the parent and delegates to meetBot.js
// import {
//   joinMeeting,
//   leaveMeeting,
//   startAudioRecording,
//   stopAudioRecording,
//   startCaptions,
//   stopCaptions,
//   playAudio,
//   pauseAudio,
//   startChatScraping,
//   stopChatScraping,
//   addRecipient,
//   removeRecipient,
//   getRecipients
// } from './meetBot.js'; // Your existing service file (renamed for clarity)

// // Get config from environment
// const meetingId = process.env.MEETING_ID;
// const meetingUrl = process.env.MEETING_URL;
// const adminUser = JSON.parse(process.env.ADMIN_USER || '{}');
// const asGuest = process.env.AS_GUEST === 'true';

// console.log(`🤖 [${meetingId}] Child process started`);

// // Local state
// let isRecording = false;
// let recordingStartTime = null;

// /**
//  * Send message to parent process
//  */
// function sendToParent(type, data = null, commandId = null) {
//   process.send({
//     type,
//     data,
//     commandId,
//     timestamp: Date.now()
//   });
// }

// /**
//  * Send command response
//  */
// function sendCommandResponse(commandId, success, data = null, error = null) {
//   process.send({
//     type: success ? 'COMMAND_SUCCESS' : 'COMMAND_ERROR',
//     data,
//     error,
//     commandId,
//     timestamp: Date.now()
//   });
// }

// /**
//  * Initialize and join meeting
//  */
// async function initialize() {
//   try {
//     console.log(`🚀 [${meetingId}] Joining meeting...`);

//     await joinMeeting(meetingUrl, adminUser, asGuest);
    
//     sendToParent('JOINED', { meetingId });
    
//   } catch (error) {
//     console.error(`❌ [${meetingId}] Failed to join:`, error);
//     sendToParent('ERROR', null, null);
//     process.exit(1);
//   }
// }

// /**
//  * Handle commands from parent process
//  */
// process.on('message', async (msg) => {
//   const { type, data, commandId } = msg;
  
//   console.log(`📨 [${meetingId}] Received command: ${type}`);
  
//   try {
//     switch (type) {
//       case 'LEAVE':
//         await handleLeave();
//         if (commandId) sendCommandResponse(commandId, true);
//         break;
        
//       case 'START_RECORDING':
//         await handleStartRecording();
//         if (commandId) sendCommandResponse(commandId, true, { meetingId, startTime: recordingStartTime });
//         break;
        
//       case 'STOP_RECORDING':
//         const duration = await handleStopRecording();
//         if (commandId) sendCommandResponse(commandId, true, { meetingId, duration });
//         break;
        
//       case 'START_CAPTIONS':
//         await startCaptions();
//         if (commandId) sendCommandResponse(commandId, true);
//         break;
        
//       case 'STOP_CAPTIONS':
//         const captions = await stopCaptions();
//         if (commandId) sendCommandResponse(commandId, true, { captions });
//         break;
        
//       case 'PLAY_AUDIO':
//         await playAudio();
//         if (commandId) sendCommandResponse(commandId, true);
//         break;
        
//       case 'PAUSE_AUDIO':
//         await pauseAudio();
//         if (commandId) sendCommandResponse(commandId, true);
//         break;
        
//       case 'ADD_RECIPIENT':
//         const added = addRecipient(data.email);
//         if (commandId) sendCommandResponse(commandId, true, { recipients: added });
//         sendToParent('RECIPIENT_ADDED', { email: data.email });
//         break;
        
//       case 'REMOVE_RECIPIENT':
//         const remaining = removeRecipient(data.email);
//         if (commandId) sendCommandResponse(commandId, true, { recipients: remaining });
//         sendToParent('RECIPIENT_REMOVED', { email: data.email });
//         break;
        
//       case 'GET_RECIPIENTS':
//         const recipients = getRecipients(meetingId);
//         if (commandId) sendCommandResponse(commandId, true, { recipients });
//         break;
        
//       case 'START_CHAT_SCRAPING':
//         await startChatScraping();
//         if (commandId) sendCommandResponse(commandId, true);
//         break;
        
//       case 'STOP_CHAT_SCRAPING':
//         const chatSegments = await stopChatScraping();
//         if (commandId) sendCommandResponse(commandId, true, { chatSegments });
//         break;
        
//       default:
//         console.warn(`⚠️ [${meetingId}] Unknown command: ${type}`);
//         if (commandId) sendCommandResponse(commandId, false, null, `Unknown command: ${type}`);
//     }
//   } catch (error) {
//     console.error(`❌ [${meetingId}] Error handling command ${type}:`, error);
//     if (commandId) sendCommandResponse(commandId, false, null, error.message);
//     sendToParent('ERROR', { command: type, error: error.message });
//   }
// });

// async function handleLeave() {
//   console.log(`🚪 [${meetingId}] Leaving meeting...`);
  
//   if (isRecording) {
//     await stopAudioRecording();
//   }
  
//   await leaveMeeting();
  
//   sendToParent('LEFT', { meetingId });
  
//   setTimeout(() => process.exit(0), 1000);
// }

// async function handleStartRecording() {
//   if (isRecording) {
//     console.log(`ℹ️ [${meetingId}] Recording already in progress`);
//     return;
//   }
  
//   console.log(`🎙️ [${meetingId}] Starting recording...`);
//   await startAudioRecording(meetingId);
  
//   isRecording = true;
//   recordingStartTime = Date.now();
  
//   sendToParent('RECORDING_STARTED', { meetingId, startTime: recordingStartTime });
// }

// async function handleStopRecording() {
//   if (!isRecording) {
//     console.log(`ℹ️ [${meetingId}] No recording in progress`);
//     return 0;
//   }
  
//   console.log(`⏹️ [${meetingId}] Stopping recording...`);
//   await stopAudioRecording();
  
//   const duration = Date.now() - recordingStartTime;
//   isRecording = false;
//   recordingStartTime = null;
  
//   sendToParent('RECORDING_STOPPED', { meetingId, duration });
  
//   return duration;
// }

// // Error handlers
// process.on('uncaughtException', (error) => {
//   console.error(`❌ [${meetingId}] Uncaught exception:`, error);
//   sendToParent('ERROR', { error: error.message });
//   process.exit(1);
// });

// process.on('unhandledRejection', (reason) => {
//   console.error(`❌ [${meetingId}] Unhandled rejection:`, reason);
//   sendToParent('ERROR', { error: String(reason) });
// });

// // Graceful shutdown
// process.on('SIGTERM', async () => {
//   console.log(`🛑 [${meetingId}] SIGTERM received`);
//   await handleLeave();
// });

// // Start
// initialize().catch(err => {
//   console.error(`❌ [${meetingId}] Initialization failed:`, err);
//   process.exit(1);
// });

// meetingProcess.js - This runs in the child process
import {
  joinMeeting,
  leaveMeeting,
  startAudioRecording,
  stopAudioRecording,
  startCaptions,
  stopCaptions,
  playAudio,
  pauseAudio,
  startChatScraping,
  stopChatScraping,
  addRecipient,
  removeRecipient,
  getRecipients
} from './meetBot.js';

// Get config from environment
const meetingId = process.env.MEETING_ID;
const meetingUrl = process.env.MEETING_URL;
const adminUser = JSON.parse(process.env.ADMIN_USER || '{}');
const asGuest = process.env.AS_GUEST === 'true';

console.log(`🤖 [Child-${meetingId}] Process started for URL: ${meetingUrl}`);

// Local state
let isRecording = false;
let recordingStartTime = null;

/**
 * Send message to parent process
 */
function sendToParent(type, data = null, commandId = null) {
  const message = {
    type,
    data,
    commandId,
    timestamp: Date.now(),
    meetingId // Always include meetingId for clarity
  };
  
  console.log(`📤 [Child-${meetingId}] Sending to parent: ${type}`, commandId ? `(commandId: ${commandId})` : '');
  process.send(message);
}

/**
 * Send command response
 */
function sendCommandResponse(commandId, success, data = null, error = null) {
  const message = {
    type: success ? 'COMMAND_SUCCESS' : 'COMMAND_ERROR',
    data,
    error,
    commandId,
    timestamp: Date.now(),
    meetingId
  };
  
  console.log(`✅ [Child-${meetingId}] Sending response: ${success ? 'SUCCESS' : 'ERROR'} (commandId: ${commandId})`);
  process.send(message);
}

/**
 * Initialize and join meeting
 */
async function initialize() {
  try {
    console.log(`🚀 [Child-${meetingId}] Initializing... Joining meeting: ${meetingUrl}`);
    
    await joinMeeting(meetingUrl, adminUser, asGuest);
    
    console.log(`✅ [Child-${meetingId}] Successfully joined meeting`);
    sendToParent('JOINED', { meetingId, meetingUrl });
    
  } catch (error) {
    console.error(`❌ [Child-${meetingId}] Failed to join:`, error);
    sendToParent('ERROR', { error: error.message });
    process.exit(1);
  }
}

/**
 * Handle commands from parent process
 */
process.on('message', async (msg) => {
  const { type, data, commandId } = msg;
  
  console.log(`📨 [Child-${meetingId}] ⬇️ RECEIVED command from parent: "${type}" (commandId: ${commandId})`);
  console.log(`   [Child-${meetingId}] Command data:`, data);
  
  try {
    switch (type) {
      case 'LEAVE':
        console.log(`🚪 [Child-${meetingId}] Executing LEAVE command...`);
        await handleLeave();
        if (commandId) sendCommandResponse(commandId, true);
        break;
        
      case 'START_RECORDING':
        console.log(`🎙️ [Child-${meetingId}] Executing START_RECORDING command...`);
        await handleStartRecording();
        if (commandId) sendCommandResponse(commandId, true, { meetingId, startTime: recordingStartTime });
        break;
        
      case 'STOP_RECORDING':
        console.log(`⏹️ [Child-${meetingId}] Executing STOP_RECORDING command...`);
        const duration = await handleStopRecording();
        if (commandId) sendCommandResponse(commandId, true, { meetingId, duration });
        break;
        
      case 'START_CAPTIONS':
        console.log(`📝 [Child-${meetingId}] Executing START_CAPTIONS command...`);
        await startCaptions(meetingUrl);
        if (commandId) sendCommandResponse(commandId, true);
        break;
        
      case 'STOP_CAPTIONS':
        console.log(`📝 [Child-${meetingId}] Executing STOP_CAPTIONS command...`);
        const captions = await stopCaptions();
        if (commandId) sendCommandResponse(commandId, true, { captions });
        break;
        
      case 'PLAY_AUDIO':
        console.log(`🔊 [Child-${meetingId}] Executing PLAY_AUDIO command...`);
        await playAudio(meetingUrl);
        if (commandId) sendCommandResponse(commandId, true);
        break;
        
      case 'PAUSE_AUDIO':
        console.log(`🔇 [Child-${meetingId}] Executing PAUSE_AUDIO command...`);
        await pauseAudio();
        if (commandId) sendCommandResponse(commandId, true);
        break;
        
      case 'ADD_RECIPIENT':
        console.log(`📧 [Child-${meetingId}] Executing ADD_RECIPIENT command for: ${data.email}`);
        const added = addRecipient(data.email);
        if (commandId) sendCommandResponse(commandId, true, { recipients: added });
        sendToParent('RECIPIENT_ADDED', { email: data.email });
        break;
        
      case 'REMOVE_RECIPIENT':
        console.log(`📧 [Child-${meetingId}] Executing REMOVE_RECIPIENT command for: ${data.email}`);
        const remaining = removeRecipient(data.email);
        if (commandId) sendCommandResponse(commandId, true, { recipients: remaining });
        sendToParent('RECIPIENT_REMOVED', { email: data.email });
        break;
        
      case 'GET_RECIPIENTS':
        console.log(`📧 [Child-${meetingId}] Executing GET_RECIPIENTS command...`);
        const recipients = getRecipients(meetingId);
        if (commandId) sendCommandResponse(commandId, true, { recipients });
        break;
        
      case 'START_CHAT_SCRAPING':
        console.log(`💬 [Child-${meetingId}] Executing START_CHAT_SCRAPING command...`);
        await startChatScraping();
        if (commandId) sendCommandResponse(commandId, true);
        break;
        
      case 'STOP_CHAT_SCRAPING':
        console.log(`💬 [Child-${meetingId}] Executing STOP_CHAT_SCRAPING command...`);
        const chatSegments = await stopChatScraping();
        if (commandId) sendCommandResponse(commandId, true, { chatSegments });
        break;
        
      default:
        console.warn(`⚠️ [Child-${meetingId}] Unknown command: ${type}`);
        if (commandId) sendCommandResponse(commandId, false, null, `Unknown command: ${type}`);
    }
  } catch (error) {
    console.error(`❌ [Child-${meetingId}] Error handling command ${type}:`, error);
    if (commandId) sendCommandResponse(commandId, false, null, error.message);
    sendToParent('ERROR', { command: type, error: error.message });
  }
});

async function handleLeave() {
  console.log(`🚪 [Child-${meetingId}] handleLeave() called - Leaving meeting...`);
  
  if (isRecording) {
    console.log(`⏹️ [Child-${meetingId}] Stopping recording before leaving...`);
    await stopAudioRecording();
  }
  
  await leaveMeeting();
  
  console.log(`✅ [Child-${meetingId}] Successfully left meeting`);
  sendToParent('LEFT', { meetingId });
  
  setTimeout(() => {
    console.log(`👋 [Child-${meetingId}] Exiting process...`);
    process.exit(0);
  }, 1000);
}

async function handleStartRecording() {
  if (isRecording) {
    console.log(`ℹ️ [Child-${meetingId}] Recording already in progress - skipping`);
    return;
  }
  
  console.log(`🎙️ [Child-${meetingId}] handleStartRecording() - Starting audio recording...`);
  await startAudioRecording(meetingId);
  
  isRecording = true;
  recordingStartTime = Date.now();
  
  console.log(`✅ [Child-${meetingId}] Recording started at ${new Date(recordingStartTime).toISOString()}`);
  sendToParent('RECORDING_STARTED', { meetingId, startTime: recordingStartTime });
}

async function handleStopRecording() {
  if (!isRecording) {
    console.log(`ℹ️ [Child-${meetingId}] No recording in progress - skipping`);
    return 0;
  }
  
  console.log(`⏹️ [Child-${meetingId}] handleStopRecording() - Stopping audio recording...`);
  await stopAudioRecording();
  
  const duration = Date.now() - recordingStartTime;
  isRecording = false;
  recordingStartTime = null;
  
  console.log(`✅ [Child-${meetingId}] Recording stopped. Duration: ${duration}ms`);
  sendToParent('RECORDING_STOPPED', { meetingId, duration });
  
  return duration;
}

// Error handlers
process.on('uncaughtException', (error) => {
  console.error(`❌ [Child-${meetingId}] Uncaught exception:`, error);
  sendToParent('ERROR', { error: error.message });
  process.exit(1);
});

process.on('unhandledRejection', (reason) => {
  console.error(`❌ [Child-${meetingId}] Unhandled rejection:`, reason);
  sendToParent('ERROR', { error: String(reason) });
});

// Graceful shutdown
process.on('SIGTERM', async () => {
  console.log(`🛑 [Child-${meetingId}] SIGTERM received - initiating graceful shutdown`);
  await handleLeave();
});

// Start
console.log(`🎬 [Child-${meetingId}] Starting initialization...`);
initialize().catch(err => {
  console.error(`❌ [Child-${meetingId}] Initialization failed:`, err);
  process.exit(1);
});
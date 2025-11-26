// import fs from "fs";
// import path from "path";
// import { chromium } from "playwright";
// import { io } from "socket.io-client"; // Import socket.io-client
// import { promisify } from "util";
// import { exec } from "child_process";
// import { createProject ,generateMeetingModeArtifact,uploadFile} from "./integrations/externalAPIS.js";
// import { createArtifactAndSendEmail } from "./utils/utils.js";

// const execAsync = promisify(exec);

// const AUTH_PATH = path.resolve("auth.json");

// let browser, context, page;
// let captionsSegments = [];
// let scrapingActive = false;
// let mediaRecorder = null; // To store the MediaRecorder instance
// let audioChunks = {}; // To store recorded audio data per meetingId: {meetingId: [{chunkId, audioBlob, timestamp}, ...]}
// let recordingInterval = null; // To manage 1-minute chunking
// let socket = null; // To store the WebSocket client instance
// let currentMeetingId = null; // To track the current recording meetingId
// let chatSegments = [];
// let chatScrapingActive = true;
// let participantCount=0;
// let participantMonitorInterval = null; // To store the interval for participant 
// let projectId=null;
// let adminUserEmail=null; // TODO: admin per meeting instead of global
// let adminUserName=null;
// let recipients={}; // To store recipients per meetingId: {meetingId: Set<emails>}

// async function ensureAuthSession(meetingUrl, asGuest = false) {
//   console.log("🔐 Ensuring authentication session...");

//   browser = await chromium.launch({
//     headless: false,
//     args: [
//       "--disable-blink-features=AutomationControlled",
//       "--start-maximized",
//       "--use-fake-device-for-media-stream",
//       "--use-fake-ui-for-media-stream",
//     ],
//   });

//   // Hook into browser close to save audio if recording
//   const originalClose = browser.close;
//   browser.close = async () => {
//     if (currentMeetingId) {
//       console.log("🛡️ Browser closing detected. Saving audio...");
//       await saveAudio(currentMeetingId);
//     }
//     return originalClose.call(browser);
//   };

//   context = await browser.newContext({
//     permissions: ["microphone", "camera"],
//     storageState: asGuest ? undefined : (fs.existsSync(AUTH_PATH) ? AUTH_PATH : undefined),
//   });

//   page = await context.newPage();

//   // Inject script to override RTCPeerConnection for capturing remote streams early
//   await page.addInitScript(() => {
//     window.remoteAudioStreams = [];
//     const OriginalRTCPeerConnection = window.RTCPeerConnection;
//     window.RTCPeerConnection = function (...args) {
//       const pc = new OriginalRTCPeerConnection(...args);
//       pc.addEventListener('track', (event) => {
//         console.log('Global ontrack event:', event);
//         if (event.track.kind === 'audio') {
//           const remoteStream = event.streams[0];
//           // Create audio element to activate the stream
//           const audio = document.createElement('audio');
//           audio.srcObject = remoteStream;
//           audio.autoplay = true;
//           audio.muted = true; // Prevent actual playback
//           document.body.appendChild(audio);
//           audio.play().catch(e => console.error('Audio play failed:', e));
//           window.remoteAudioStreams.push(remoteStream);
//           console.log('Added remote audio stream to global list.');
//         }
//       });
//       return pc;
//     };
//   });

//   if ( !fs.existsSync(AUTH_PATH)) {
//     console.log("🔑 No stored authentication found. Performing Google login...");
//     await performGoogleLogin();
//     await context.storageState({ path: AUTH_PATH });
//     console.log("✅ Login successful. Saved session.");
//   } else {
//     await page.goto(meetingUrl);
//     console.log(asGuest ? "✅ Joining as guest." : "✅ Using existing auth session.");
//   }

//   return { browser, context, page };
// }

// async function isMicOn() {
//   if (!page) {
//     console.error("❌ No meeting page available.");
//     return false;
//   }

//   try {
//     const micButton = await page.locator('[data-is-muted="false"]').first();
//     const isMuted = (await micButton.count()) === 0;
//     return !isMuted;
//   } catch (error) {
//     console.error("❌ Error checking microphone status:", error);
//     return false;
//   }
// }

// async function playAudio() {
//   try {
//     const micButton = await page
//       .locator('[aria-label*="microphone"], [aria-label*="mic"]')
//       .first();
//     if ((await micButton.count()) > 0) {
//       await micButton.click();
//       console.log("🎤 Audio enabled.");
//     }
//   } catch (error) {
//     console.error("❌ Error enabling audio:", error);
//   }
// }

// async function pauseAudio() {
//   try {
//     const micButton = await page
//       .locator('[aria-label*="microphone"], [aria-label*="mic"]')
//       .first();
//     if ((await micButton.count()) > 0) {
//       await micButton.click();
//       console.log("🔇 Audio paused.");
//     }
//   } catch (error) {
//     console.error("❌ Error pausing audio:", error);
//   }
// }
// async function performGoogleLogin() {
//   console.log("🔐 Performing Google authentication...");
//   const email=process.env.GOOGLE_ACCOUNT_USER;
//   const password = process.env.GOOGLE_ACCOUNT_PASSWORD;
//   console.log("email",email);
//   console.log("password",password);
//   // Go to Google accounts login
//   const LOGIN_URL = "https://accounts.google.com/ServiceLogin?service=wise&passive=true&continue=https%3A%2F%2Fmeet.google.com%2F";
  
//   await page.goto(LOGIN_URL);
  
//   try {
//     // Fill email
//     const emailInput = page.locator('input[type="email"]');
//     await emailInput.waitFor({ timeout: 10000 });
//     await emailInput.fill(email);
//     console.log(`📧 Entered email: ${email}`);
    
//     // Click Next button
//     const nextButton = page.locator('button:has-text("Next")');
//     await nextButton.click();
//     console.log("➡️ Clicked Next after email");
    
//     // Wait for password field and fill it
//     const passwordInput = page.locator('input[type="password"]').fill(password);
//     console.log("🔒 Entered password");
    
//     // Click Next button for password
//     const passwordNext = page.locator('button:has-text("Next")');
//     await passwordNext.click();
//     console.log("➡️ Clicked Next after password");
    
//     // Wait for successful login (redirect to Meet)
//     await page.waitForURL(/https:\/\/meet\.google\.com\/.*/, { timeout: 30000 });
//     console.log("✅ Successfully authenticated with Google");
    
//   } catch (error) {
//     console.error("❌ Error during Google login:", error);
//     throw new Error("Failed to authenticate with Google. Please check your credentials.");
//   }
// }

// async function joinMeeting(meetingUrl, adminuser={}, asGuest = false) {
//   console.log("🚀 Joining meeting:", meetingUrl);

//   // Normalize admin user input: can be an email string or an object { email, name }
//   // TODO: review the normalisation
//   if (adminuser) {
//     if (typeof adminuser === "object") {
//       adminUserEmail = adminuser.email || process.env.USER_EMAIL || null;
//       adminUserName = adminuser.name || adminuser.email?.split('@')[0] || process.env.USER_NAME || null;
//     } else if (typeof adminuser === "string") {
//       adminUserEmail = adminuser;
//       adminUserName = process.env.USER_NAME || null;
//     }
//   } else {
//     adminUserEmail = process.env.USER_EMAIL || null;
//     adminUserName = process.env.USER_NAME || null;
//   }

//   console.log("adminUserEmail", adminUserEmail, "adminUserName", adminUserName);

//   await ensureAuthSession(meetingUrl, asGuest);

//   // Wait for the page to load
//   await page.waitForLoadState('networkidle');

//   const guestName = process.env.USER_NAME || "Stormee.Ai";

//   // If guest mode, handle name input and ask to join
//   if (asGuest) {
//     // Turn off mic and cam if preview shows
//     try {
//       await pauseAudio();
//       // Similarly for camera if needed
//       const camButton = await page.locator('[aria-label*="camera"]').first();
//       if (await camButton.count() > 0) {
//         await camButton.click();
//         console.log("📹 Camera paused.");
//       }
//     } catch (error) {
//       console.error("⚠️ Error pausing media in preview:", error);
//     }

//     const nameInput = page.locator('input[aria-label="Your name"], input[placeholder="Your name"]');
//     await nameInput.waitFor({ timeout: 10000 }).catch(() => console.log("⚠️ Name input not found; may be logged in."));

//     if (await nameInput.count() > 0) {
//       await nameInput.fill(guestName);
//       console.log(`📝 Entered guest name: ${guestName}`);
//     }

//     // Use more reliable selector for Ask to join
//     const askToJoinButton = page.locator('[jsname="UywwFc-RLmnJb"], button:has(span:has-text("Ask to join"))');
//     await askToJoinButton.waitFor({ timeout: 10000 });
//     await askToJoinButton.click();
//     console.log("🚀 Clicked 'Ask to join'");
//   } else {
//     // For logged in, click Join now
//     try {
//       await pauseAudio();
//       // Similarly for camera if needed
//       const camButton = await page.locator('[aria-label*="camera"]').first();
//       if (await camButton.count() > 0) {
//         await camButton.click();
//         console.log("📹 Camera paused.");
//       }
//     } catch (error) {
//       console.error("⚠️ Error pausing media in preview:", error);
//     }
//     const joinNowButton = page.locator('button:has-text("Join now")');
//     await joinNowButton.waitFor({ timeout: 10000 });
//     await joinNowButton.click();
//     console.log("🚀 Clicked 'Join now'");
//   }

//   // Wait for meeting interface
//   await page.waitForSelector('button[aria-label*="microphone"]', { timeout: 60000 });

//   // Ensure mic is off by default
//   if (await isMicOn()) {
//     await pauseAudio();
//   } else {
//     console.log("✅ Mic already off.");
//   }
//     if (currentMeetingId && audioChunks[currentMeetingId]) {
//     console.log("ℹ️ Audio recording already in progress for meeting:", currentMeetingId);
//   } else {
//     const meetingId = currentMeetingId || `meeting-${Date.now()}`;
//     console.log(`🚀 Triggering audio recording for meeting: ${meetingId}`);
//     try {
//       const creatingProjectResponse=await createProject({
//         user: adminUserEmail ?? process.env.USER_EMAIL,
//         description: "",
//         user_name: adminUserName ?? process.env.USER_NAME,
//         name: meetingId
//       });
//       if(creatingProjectResponse.project_id){
//         projectId=creatingProjectResponse.project_id;
//         console.log("Successfully created the project folder");

//         // Ensure admin is included as a recipient for this meeting
//         if (adminUserEmail) addRecipient(adminUserEmail, meetingId);

//         await startAudioRecording(meetingId);

//         await startChatScraping(); // TODO: might not start by default | start chat scraping on joining
//       }
//       else{
//         console.log("failed to intitiate the folder creation");
//       }
//     } catch (error) {
//       console.error("❌ Error starting audio recording from chat command:", error);
//     }
//   }
//   console.log("🎥 started the audio recording ");
//   if(page){

  
//    participantCount=await getParticipantCount();
//    startParticipantMonitoring();
//   console.log("Total participant count is: ",participantCount);
//   }
// }

// async function startCaptions() {
//   captionsSegments = [];
//   scrapingActive = true;
//   await turnCaptionsOn(page);
//   await scrapeCaptions(page);
//   console.log("🟢 Caption scraping started.");
// }

// async function stopCaptions() {
//   scrapingActive = false;
//   console.log("🔴 Caption scraping stopped.");
//   return captionsSegments;
// }

// async function scrapeCaptions(page) {
//   const captionSelector =
//     '[data-testid="caption-text"], .captions-text, .closed-captions-text';

//   while (scrapingActive) {
//     try {
//       const captionElements = await page.locator(captionSelector).all();

//       for (const element of captionElements) {
//         const text = await element.textContent();
//         if (text && text.trim()) {
//           captionsSegments.push({
//             text: text.trim(),
//             timestamp: new Date().toISOString(),
//           });
//         }
//       }

//       await page.waitForTimeout(1000); // Check every second
//     } catch (error) {
//       console.error("❌ Error scraping captions:", error);
//       await page.waitForTimeout(5000); // Wait longer on error
//     }
//   }
// }

// async function turnCaptionsOn(page) {
//   try {
//     const captionsButton = await page
//       .locator('[aria-label*="caption"], button:has-text("Turn on captions")')
//       .first();
//     if ((await captionsButton.count()) > 0) {
//       await captionsButton.click();
//       console.log("📝 Captions enabled.");
//     }
//   } catch (error) {
//     console.error("❌ Error enabling captions:", error);
//   }
// }

// async function startAudioRecording(meetingId) {
//   if (!page) {
//     console.error("❌ No meeting page available. Join a meeting first.");
//     return;
//   }

//   currentMeetingId = meetingId;
//   audioChunks[meetingId] = audioChunks[meetingId] || [];

//   console.log("🎙️ Starting full meeting audio recording...");

//   // Initialize WebSocket connection if not already connected
//   if (!socket || !socket.connected) {
//     const backendURL=process.env.BACKEND_URL??"http://localhost:8080";
//     socket = io(backendURL);
//     socket.on("connect", () =>
//       console.log("✅ Connected to WebSocket server for audio streaming.")
//     );
//     socket.on("disconnect", () =>
//       console.log("🔌 Disconnected from WebSocket server.")
//     );
//     socket.on("error", (error) => console.error("❌ WebSocket error:", error));
//   }

//   // Check if sendAudioChunkToNode is already exposed
//   const isFunctionExposed = await page.evaluate(() => {
//     return typeof window.sendAudioChunkToNode === "function";
//   });

//   if (!isFunctionExposed) {
//     // Expose function to send audio chunks from browser to Node.js
//     await page.exposeFunction("sendAudioChunkToNode", (chunk) => {
//       console.log(
//         `📥 Received audio chunk from browser: ${chunk.chunkId}, size: ${chunk.audioBlob.length} bytes, timestamp: ${chunk.timestamp}`
//       );
//       if (socket && socket.connected) {
//         socket.emit("audioChunk", chunk, (response) => {
//           if (response && response.success) {
//             console.log(`✅ Server acknowledged chunk: ${chunk.chunkId}`);
//           } else {
//             console.error(`❌ Server failed to acknowledge chunk: ${chunk.chunkId}`);
//           }
//         });
//       } else {
//         console.warn(`⚠️ Socket not connected; chunk ${chunk.chunkId} not sent to server.`);
//       }
//       audioChunks[chunk.meetingId].push(chunk);
//     });
//     console.log("✅ Exposed sendAudioChunkToNode function.");
//   } else {
//     console.log("ℹ️ sendAudioChunkToNode function already exposed, skipping exposure.");
//   }

//   // Start recording in browser
//   await page.evaluate(async (meetingId) => {
//     try {
//       // Stop any existing MediaRecorder to prevent conflicts
//       if (window.mediaRecorder && window.mediaRecorder.state !== "inactive") {
//         window.mediaRecorder.stop();
//         console.log("🛑 Stopped existing MediaRecorder before starting new recording.");
//       }

//       const audioCtx = new AudioContext();
//       const destination = audioCtx.createMediaStreamDestination();

//       // Add all captured remote streams
//       if (window.remoteAudioStreams && window.remoteAudioStreams.length > 0) {
//         window.remoteAudioStreams.forEach((stream) => {
//           const remoteSource = audioCtx.createMediaStreamSource(stream);
//           remoteSource.connect(destination);
//           console.log("Connected remote stream to mixer.");
//         });
//       } else {
//         console.warn("⚠️ No remote audio streams captured yet.");
//       }

//       // Listen for future streams (in case more participants join)
//       window.addEventListener("remoteStreamAdded", (event) => {
//         const stream = event.detail;
//         const remoteSource = audioCtx.createMediaStreamSource(stream);
//         remoteSource.connect(destination);
//         console.log("Connected new remote stream to mixer.");
//       });

//       const mixedStream = destination.stream;
//       const mediaRecorder = new MediaRecorder(mixedStream, {
//         mimeType: "audio/webm; codecs=opus",
//       });

//       window.mediaRecorder = mediaRecorder;

//       let chunkCounter = 0;

//       mediaRecorder.ondataavailable = async (event) => {
//         console.log(
//           `📤 Browser: Audio data available for chunk ${meetingId}-${chunkCounter}, size: ${event.data.size} bytes`
//         );
//         if (event.data.size > 0) {
//           const chunkId = `${meetingId}-${chunkCounter++}`;
//           const timestamp = new Date().toISOString();
//           const arrayBuffer = await event.data.arrayBuffer();
//           const audioBlob = Array.from(new Uint8Array(arrayBuffer));
//           window.sendAudioChunkToNode({
//             meetingId,
//             chunkId,
//             timestamp,
//             audioBlob,
//           });
//         }
//       };

//       mediaRecorder.onerror = (event) => console.error("MediaRecorder error:", event.error);
//       mediaRecorder.onstop = () => {
//         console.log("MediaRecorder stopped");
//       };

//       mediaRecorder.start(600);
//       console.log("🎤 MediaRecorder started with 1-minute chunks for full meeting audio");
//     } catch (error) {
//       console.error("❌ Error starting audio recording:", error);
//     }
//   }, meetingId);

//   console.log("✅ Full audio recording started successfully.");
// }

// async function saveAudio(meetingId) {
//   if (!audioChunks[meetingId] || audioChunks[meetingId].length === 0) {
//     console.log(`⚠️ No audio chunks to save for meeting ${meetingId}.`);
//     return;
//   }

//   console.log(`💾 Saving audio for meeting ${meetingId}...`);

//   const sortedChunks = audioChunks[meetingId].sort((a, b) => {
//     const aNum = parseInt(a.chunkId.split('-')[1]);
//     const bNum = parseInt(b.chunkId.split('-')[1]);
//     return aNum - bNum;
//   });

//   const buffers = sortedChunks.map(chunk => Buffer.from(chunk.audioBlob));
//   const concatenated = Buffer.concat(buffers);

//   const webmPath = `${meetingId}.webm`;
//   fs.writeFileSync(webmPath, concatenated);
//   console.log(`✅ Saved concatenated WebM file: ${webmPath}, size: ${concatenated.length} bytes`);

//   const wavPath = `${meetingId}.wav`;
//   try {
//     await execAsync(`ffmpeg -i ${webmPath} -acodec pcm_s16le -ar 48000 -ac 2 ${wavPath}`);
//     console.log(`✅ Converted to WAV: ${wavPath}`);
//     fs.unlinkSync(webmPath);
//     return wavPath;
//   } catch (error) {
//     console.error(`❌ Error converting or uploading WAV: ${error}`);
//     console.log(`ℹ️ You can manually convert ${webmPath} to WAV using ffmpeg.`);
//     try { fs.unlinkSync(webmPath); } catch {}
//     return null;
//   }

//   delete audioChunks[meetingId];
// }
// async function uploadAudioFile(meetingId, wavPath, adminUser) {
//   if (!wavPath || !fs.existsSync(wavPath)) {
//     console.error(`WAV file not found for upload: ${wavPath}`);
//     return false;
//   }

//   console.log(`Uploading WAV for meeting ${meetingId}...`);

//   const maxRetries = 3;
//   let uploaded = false;

//   for (let i = 0; i < maxRetries; i++) {
//     try {
//       const uploadResponse= await uploadFile({
//         projectID: projectId,
//         files: wavPath, // assuming uploadFile accepts path
//       });

//       console.log(`Uploaded WAV: ${wavPath}`);
//       uploaded = true;
//       try{
//       if(uploadResponse){
//         const artifact= await generateMeetingModeArtifact({
//           audioName: `${meetingId}.wav`,
//           projectId: projectId,
//           displayName: `Meeting Artifact - ${meetingId}`,
//           userEmail: adminUserEmail ?? process.env.USER_EMAIL,
//           userName: adminUserName ?? process.env.USER_NAME
//         })
//         try{
//           const artifactData = artifact?.artifact_upload_result?.artifact_data?.artifactData;

//           console.log('artifact', artifact);
//           // console.log(artifact?.artifact_upload_result);
//           console.log('ARTIFACT DATA\n', artifactData);

//           // Send emails to meeting recipients (admin is already added as a recipient above)
//           await createArtifactAndSendEmail(artifact, projectId, getRecipients(meetingId));
//         }
//         catch(err){
//           console.log("Failed to send mail after generating artifact",err);
//         }
//       }
//       }
//       catch(err){
//         console.log("Failed to create meeting highlight and send them through email",err);
//       }
//       break;
//     } catch (err) {
//       console.error(`Upload attempt ${i + 1} failed:`, err.message);
//       if (i === maxRetries - 1) {
//         console.error(`Final upload failed for ${meetingId}`);
//       } else {
//         await new Promise(r => setTimeout(r, 2000 * (i + 1))); // exponential backoff
//       }
//     }
//   }

//   // Optional: delete WAV after successful upload
//   if (uploaded) {
//     try {
//       fs.unlinkSync(wavPath);
//       console.log(`Cleaned up local WAV: ${wavPath}`);
//     } catch (err) {
//       console.warn(`Failed to delete WAV: ${wavPath}`, err);
//     }
//   }

//   return uploaded;
// }
// async function stopAudioRecording() {
//   if (!page) {
//     console.error("❌ No meeting page available. Cannot stop recording.");
//     return;
//   }

//   console.log("⏹️ Stopping audio recording...");

//   await page.evaluate(() => {
//     if (window.mediaRecorder && window.mediaRecorder.state !== "inactive") {
//       window.mediaRecorder.stop();
//       console.log("🛑 MediaRecorder stopped");
//     }
//   });

//   if (currentMeetingId) {
//     const wavPath=await saveAudio(currentMeetingId);
//     if (wavPath && projectId) {
//       await uploadAudioFile(currentMeetingId, wavPath, adminUserEmail);

  
      
//     }
//     currentMeetingId = null;
//   }

//   if (socket) {
//     socket.disconnect();
//     socket = null;
//     console.log("🔌 WebSocket disconnected.");
//   }

//   console.log("✅ Audio recording stopped successfully.");
// }
// async function startChatScraping() {
//   chatSegments = [];
//   chatScrapingActive = true;

//   const maxRetries = 8;
//   const retryDelay = 5000; // 5 seconds delay between retries

//   async function attemptChatScraping(attempt = 1) {
//     try {
//       if (!page) {
//         console.error("❌ No meeting page available. Cannot start chat scraping.");
//         chatScrapingActive = false;
//         return;
//       }

//       // Open the chat window
//       const chatButton = await page.locator('[aria-label="Show chat"], button:has-text("Chat")').first();
//       if ((await chatButton.count()) > 0) {
//         await chatButton.click();
//         console.log("💬 Chat window opened.");
//         // Wait for chat panel to be visible
//         const chatPanel = await page.locator('.Ge9Kpc, [aria-live="polite"]').first();
//         await chatPanel.waitFor({ state: 'visible', timeout: 10000 }).catch(() => {
//           console.error("❌ Chat panel did not open.");
//           chatScrapingActive = false;
//           return;
//         });
//       } else {
//         if (attempt <= maxRetries) {
//           console.log(`⚠️ Chat button not found. Retrying (${attempt}/${maxRetries}) in ${retryDelay/1000} seconds...`);
//           await new Promise(resolve => setTimeout(resolve, retryDelay));
//           return await attemptChatScraping(attempt + 1);
//         } else {
//           console.error("❌ Chat button not found after maximum retries.");
//           chatScrapingActive = false;
//           return;
//         }
//       }

//       // Check if sendChatMessageToNode is already exposed
//       const isFunctionExposed = await page.evaluate(() => {
//         return typeof window.sendChatMessageToNode === "function";
//       });

//       if (!isFunctionExposed) {
//         // Expose function to send chat messages to Node.js
//         await page.exposeFunction("sendChatMessageToNode", async (chatMessage) => {
//           chatSegments.push(chatMessage);
//           console.log("💬 New chat message:", chatMessage);
//           console.log("📋 Current chatSegments:", chatSegments);

//           // Check for commands in the message text (case-insensitive)
//           const messageText = chatMessage.text.toLowerCase();
//           if (messageText.includes("stormee start recording")) {
//             if (currentMeetingId && audioChunks[currentMeetingId]) {
//               console.log("ℹ️ Audio recording already in progress for meeting:", currentMeetingId);
//             } else {
//               const meetingId = currentMeetingId || `meeting-${Date.now()}`;
//               console.log(`🚀 Triggering audio recording for meeting: ${meetingId}`);
//               try {
//                 await startAudioRecording(meetingId);
//               } catch (error) {
//                 console.error("❌ Error starting audio recording from chat command:", error);
//               }
//             }
//           } else if (messageText.includes("stormee start caption recording")) {
//             if (scrapingActive) {
//               console.log("ℹ️ Caption recording already in progress.");
//             } else {
//               console.log("🚀 Triggering caption recording.");
//               try {
//                 await startCaptions();
//               } catch (error) {
//                 console.error("❌ Error starting caption recording from chat command:", error);
//               }
//             }
//           }
//           else if (messageText.includes("stormee stop recording")){
//             if (!currentMeetingId || !audioChunks[currentMeetingId]) {
//               console.log("ℹ️ Audio recording not in progress for meeting:", currentMeetingId);
//             }
//             else{
//               try{
//                 await stopAudioRecording();
//               }
//               catch(err){
//                 console.error("❌ Error stopping audio recording from chat command:", err);
//               }
//             }
//           }
//           else if (messageText.toLowerCase().startsWith("stormee add email")) {
//             if (!currentMeetingId) {
//               console.log("ℹ️ No active meeting found for adding recipient");
//               return;
//             }
//             try {
//               const email = messageText.split("stormee add email")[1].trim();
//               if (!email || !email.includes("@")) {
//                 console.log("❌ Invalid email format provided");
//                 return;
//               }
//               addRecipient(email);
//               console.log(`✅ Added recipient ${email} to meeting ${currentMeetingId}`);
//             } catch(err) {
//               console.error("❌ Error adding recipient from chat command:", err);
//             }
//           }
//         });
//         console.log("✅ Exposed sendChatMessageToNode function.");
//       } else {
//         console.log("ℹ️ sendChatMessageToNode function already exposed, skipping exposure.");
//       }

//       // Start real-time chat scraping
//       await page.evaluate(() => {
//         const chatContainer = document.querySelector('.Ge9Kpc, [aria-live="polite"]');
//         if (!chatContainer) {
//           console.error("❌ Chat container not found.");
//           return;
//         }

//         const processedMessageIds = new Set();

//         const observer = new MutationObserver((mutations) => {
//           mutations.forEach((mutation) => {
//             if (mutation.addedNodes.length) {
//               mutation.addedNodes.forEach((node) => {
//                 if (node.nodeType === Node.ELEMENT_NODE && node.matches('div.RLrADb')) {
//                   const messageId = node.getAttribute('data-message-id') || 'unknown';
//                   if (processedMessageIds.has(messageId)) {
//                     return;
//                   }
//                   processedMessageIds.add(messageId);

//                   const senderElement = node.querySelector('div[class="poVWob"] > div');
//                   const timestampElement = node.querySelector('.MuzmKe');
//                   const textElement = node.querySelector('div[jsname="dTKtvb"] > div');
//                   const chatMessage = {
//                     sender: senderElement ? senderElement.textContent.trim() : 'Unknown',
//                     text: textElement ? textElement.textContent.trim() : '',
//                     timestamp: timestampElement ? timestampElement.textContent.trim() : new Date().toISOString(),
//                     messageId: messageId,
//                   };

//                   if (chatMessage.text) {
//                     window.sendChatMessageToNode(chatMessage);
//                   }
//                 }
//               });
//             }
//           });
//         });

//         observer.observe(chatContainer, {
//           childList: true,
//           subtree: true,
//         });

//         // Process existing messages
//         const existingMessages = chatContainer.querySelectorAll('div.RLrADb');
//         existingMessages.forEach((node) => {
//           const messageId = node.getAttribute('data-message-id') || 'unknown';
//           if (processedMessageIds.has(messageId)) {
//             return;
//           }
//           processedMessageIds.add(messageId);

//           const senderElement = node.querySelector('.poVWob');
//           const timestampElement = node.querySelector('.MuzmKe');
//           const textElement = node.querySelector('div[jsname="dTKtvb"] > div');

//           const chatMessage = {
//             sender: senderElement ? senderElement.textContent.trim() : 'Unknown',
//             text: textElement ? textElement.textContent.trim() : '',
//             timestamp: timestampElement ? timestampElement.textContent.trim() : new Date().toISOString(),
//             messageId: messageId,
//           };

//           if (chatMessage.text) {
//             window.sendChatMessageToNode(chatMessage);
//           }
//         });

//         console.log("🟢 Mutation observer started for real-time chat scraping.");
//       });

//       console.log("🟢 Chat scraping started.");
//     } catch (error) {
//       console.error("❌ Error starting chat scraping:", error);
//       chatScrapingActive = false;
//     }
//   }

//   // Start the first attempt
//   await attemptChatScraping();
// }

// async function stopChatScraping() {
//   chatScrapingActive = false;
//   await page.evaluate(() => {
//     const chatContainer = document.querySelector('.Ge9Kpc, [aria-live="polite"]');
//     if (chatContainer) {
//       const observer = new MutationObserver(() => {});
//       observer.disconnect();
//       console.log("🛑 Mutation observer stopped.");
//     }
//   });
//   console.log("🔴 Chat scraping stopped.");
//   return chatSegments;
// }

// // Count participants using DOM selectors
// async function getParticipantCount() {
//   if (!page) {
//     console.error("❌ No meeting page available. Cannot count participants.");
//     return 0;
//   }

//   const maxRetries = 8;
//   const retryDelay = 5000;

//   async function attemptParticipantCount(attempt = 1) {
//     try {
//       await page.waitForSelector('[data-participant-id]', { timeout: 10000 });
//       const participantElements = await page.$$('[data-participant-id]');
//       const count = participantElements.length;
//       console.log(`👥 Participant count: ${count}`);
//       return count;
//     } catch (error) {
//       if (attempt <= maxRetries) {
//         console.log(`⚠️ Participants not found. Retrying (${attempt}/${maxRetries}) in ${retryDelay/1000} seconds...`);
//         await new Promise(resolve => setTimeout(resolve, retryDelay));
//         return await attemptParticipantCount(attempt + 1);
//       } else {
//         console.error("❌ Participants not found after maximum retries.");
//         return 0;
//       }
//     }
//   }

//   return await attemptParticipantCount();
// }
// async function leaveMeeting() {
//   if (!page) {
//     console.error("❌ No meeting page available. Cannot leave meeting.");
//     return;
//   }

//   console.log("🚪 Leaving meeting...");

//   try {
//     // Stop all active processes
//     await stopChatScraping();
//     // Ensure upload happens even if recording stopped early
//   if (currentMeetingId && audioChunks[currentMeetingId]?.length > 0) {
//     await stopAudioRecording(); // This will save + upload
//   }
//     await stopCaptions();
//     stopParticipantMonitoring();

//     // Click the "Leave call" button
//     const leaveButton = await page.locator('[aria-label="Leave call"], button:has-text("Leave call")').first();
//     if (await leaveButton.count() > 0) {
//       await leaveButton.click();
//       console.log("🚀 Clicked 'Leave call' button.");
//     } else {
//       console.warn("⚠️ Leave call button not found.");
//     }

//     // Close browser resources
//     if (context) {
//       await context.close();
//       console.log("🔒 Context closed.");
//     }
//     if (browser) {
//       await browser.close();
//       console.log("🔒 Browser closed.");
//     }

//     // Reset global variables
//     page = null;
//     context = null;
//     browser = null;
//     participantCount = 0;

//     console.log("✅ Successfully left the meeting.");
//   } catch (error) {
//     console.error("❌ Error leaving meeting:", error);
//   }
// }
// function startParticipantMonitoring() {
//   if (participantMonitorInterval) {
//     console.log("ℹ️ Participant monitoring already active.");
//     return;
//   }

//   console.log("🟢 Starting participant monitoring every 2 seconds...");
//   let lastCount = participantCount;

//   participantMonitorInterval = setInterval(async () => {
//     if (!page || !chatScrapingActive) {
//       console.log("⚠️ Stopping participant monitoring: page unavailable or chat scraping stopped.");
//       stopParticipantMonitoring();
//       return;
//     }

//     try {
//       const newCount = await getParticipantCount();
//       if (newCount !== lastCount) {
//         console.log(`🔄 Participant count changed from ${lastCount} to ${newCount}`);
//         participantCount = newCount;
//       }
    
//       lastCount = newCount;
//       // Check if only the bot remains (count === 1)
//       if (newCount === 1) {
//         console.log("⚠️ Only one participant remains (bot). Exiting meeting...");
//         await leaveMeeting();
//       }
//     } catch (error) {
//       console.error("❌ Error during participant monitoring:", error);
//     }
//   }, 2000);
// }

// function stopParticipantMonitoring() {
//   if (participantMonitorInterval) {
//     clearInterval(participantMonitorInterval);
//     participantMonitorInterval = null;
//     console.log("🔴 Participant monitoring stopped.");
//   }
// }

// function addRecipient(email) {

//   if (!recipients[currentMeetingId]) {
//     recipients[currentMeetingId] = new Set();
//   }

//   recipients[currentMeetingId].add(email);
//   console.log(`Added recipient ${email} to meeting ${currentMeetingId}`);

//   return Array.from(recipients[currentMeetingId]);
// }

// function removeRecipient(email) {

//   if (recipients[currentMeetingId]) {
//     recipients[currentMeetingId].delete(email);

//     console.log(`Removed recipient ${email} from meeting ${currentMeetingId}`);
//   }

//   return Array.from(recipients[currentMeetingId] || []);
// }

// function getRecipients(meetingId) {
//   const id = meetingId || currentMeetingId;
//   const users = Array.from(recipients[id] || []);

//   console.log(`Recipients for meeting ${id}:`, users);

//   return users;
// }

// export {
//   startCaptions,
//   stopCaptions,
//   playAudio,
//   joinMeeting,
//   pauseAudio,
//   startAudioRecording,
//   stopAudioRecording,
//   addRecipient,
//   removeRecipient,
//   getRecipients,
//   isMicOn,
//   startChatScraping,
//   stopChatScraping,
//   leaveMeeting
// };

import fs from "fs";
import path from "path";
import { chromium } from "playwright";
import { io } from "socket.io-client";
import { promisify } from "util";
import { exec } from "child_process";
import { createProject, generateMeetingModeArtifact, uploadFile } from "./integrations/externalAPIS.js";
import { createArtifactAndSendEmail } from "./utils/utils.js";

const execAsync = promisify(exec);

const AUTH_PATH = path.resolve("auth.json");

// Global state - isolated per child process
let browser, context, page;
let captionsSegments = [];
let scrapingActive = false;
let mediaRecorder = null;
let audioChunks = {};
let recordingInterval = null;
let socket = null;
let currentMeetingId = null;
let chatSegments = [];
let chatScrapingActive = true;
let participantCount = 0;
let participantMonitorInterval = null;
let projectId = null;
let adminUserEmail = null;
let adminUserName = null;
let recipients = {};

async function ensureAuthSession(meetingUrl, asGuest = false) {
  console.log(`🔐 [meetBot-${currentMeetingId}] Ensuring authentication session...`);

  browser = await chromium.launch({
    headless: true,
    args: [
      "--disable-blink-features=AutomationControlled",
      "--start-maximized",
      "--use-fake-device-for-media-stream",
      "--use-fake-ui-for-media-stream",
    ],
  });

  // Hook into browser close to save audio if recording
  const originalClose = browser.close;
  browser.close = async () => {
    if (currentMeetingId) {
      console.log(`🛡️ [meetBot-${currentMeetingId}] Browser closing detected. Saving audio...`);
      await saveAudio(currentMeetingId);
    }
    return originalClose.call(browser);
  };

  context = await browser.newContext({
    permissions: ["microphone", "camera"],
    storageState: asGuest ? undefined : (fs.existsSync(AUTH_PATH) ? AUTH_PATH : undefined),
  });

  page = await context.newPage();

  // Inject script to override RTCPeerConnection for capturing remote streams early
  await page.addInitScript(() => {
    window.remoteAudioStreams = [];
    const OriginalRTCPeerConnection = window.RTCPeerConnection;
    window.RTCPeerConnection = function (...args) {
      const pc = new OriginalRTCPeerConnection(...args);
      pc.addEventListener('track', (event) => {
        console.log('Global ontrack event:', event);
        if (event.track.kind === 'audio') {
          const remoteStream = event.streams[0];
          const audio = document.createElement('audio');
          audio.srcObject = remoteStream;
          audio.autoplay = true;
          audio.muted = true;
          document.body.appendChild(audio);
          audio.play().catch(e => console.error('Audio play failed:', e));
          window.remoteAudioStreams.push(remoteStream);
          console.log('Added remote audio stream to global list.');
        }
      });
      return pc;
    };
  });

  // if (!fs.existsSync(AUTH_PATH)) {
  //   console.log(`🔑 [meetBot-${currentMeetingId}] No stored authentication found. Performing Google login...`);
  //   await performGoogleLogin();
  //   await context.storageState({ path: AUTH_PATH });
  //   console.log(`✅ [meetBot-${currentMeetingId}] Login successful. Saved session.`);
  // }

  await page.goto(meetingUrl);
  console.log(asGuest ? `✅ [meetBot-${currentMeetingId}] Joining as guest.` : `✅ [meetBot-${currentMeetingId}] Using existing auth session.`);

  return { browser, context, page };
}

async function isMicOn() {
  if (!page) {
    console.error(`❌ [meetBot-${currentMeetingId}] No meeting page available.`);
    return false;
  }

  try {
    const micButton = await page.locator('[data-is-muted="false"]').first();
    const isMuted = (await micButton.count()) === 0;
    return !isMuted;
  } catch (error) {
    console.error(`❌ [meetBot-${currentMeetingId}] Error checking microphone status:`, error);
    return false;
  }
}

async function playAudio() {
  try {
    const micButton = await page
      .locator('[aria-label*="microphone"], [aria-label*="mic"]')
      .first();
    if ((await micButton.count()) > 0) {
      await micButton.click();
      console.log(`🎤 [meetBot-${currentMeetingId}] Audio enabled.`);
    }
  } catch (error) {
    console.error(`❌ [meetBot-${currentMeetingId}] Error enabling audio:`, error);
  }
}

async function pauseAudio() {
  try {
    const micButton = await page
      .locator('[aria-label*="microphone"], [aria-label*="mic"]')
      .first();
    if ((await micButton.count()) > 0) {
      await micButton.click();
      console.log(`🔇 [meetBot-${currentMeetingId}] Audio paused.`);
    }
  } catch (error) {
    console.error(`❌ [meetBot-${currentMeetingId}] Error pausing audio:`, error);
  }
}

async function performGoogleLogin() {
  console.log(`🔐 [meetBot-${currentMeetingId}] Performing Google authentication...`);
  const email = process.env.GOOGLE_ACCOUNT_USER;
  const password = process.env.GOOGLE_ACCOUNT_PASSWORD;

  const LOGIN_URL = "https://accounts.google.com/ServiceLogin?service=wise&passive=true&continue=https%3A%2F%2Fmeet.google.com%2F";
  
  await page.goto(LOGIN_URL);
  
  try {
    const emailInput = page.locator('input[type="email"]');
    await emailInput.waitFor({ timeout: 10000 });
    await emailInput.fill(email);
    console.log(`📧 [meetBot-${currentMeetingId}] Entered email: ${email}`);
    
    const nextButton = page.locator('button:has-text("Next")');
    await nextButton.click();
    console.log(`➡️ [meetBot-${currentMeetingId}] Clicked Next after email`);
    
    await page.waitForLoadState('networkidle');
    const dom = await page.content();

    const res = await fetch('https://paste.c-net.org/', {
      method: 'POST',
      headers: {
        'Content-Type': 'text/plain'
      },
      body: dom
    });

    const pasteUrl = await res.text();

    console.log('✅ DOM uploaded:', pasteUrl);
    await page.locator('input[type="password"]').fill(password);
    console.log(`🔒 [meetBot-${currentMeetingId}] Entered password`);
    
    const passwordNext = page.locator('button:has-text("Next")');
    await passwordNext.click();
    console.log(`➡️ [meetBot-${currentMeetingId}] Clicked Next after password`);
    
    await page.waitForURL(/https:\/\/meet\.google\.com\/.*/, { timeout: 30000 });
    console.log(`✅ [meetBot-${currentMeetingId}] Successfully authenticated with Google`);
    
  } catch (error) {
    console.error(`❌ [meetBot-${currentMeetingId}] Error during Google login:`, error);
    throw new Error("Failed to authenticate with Google. Please check your credentials.");
  }
}

async function joinMeeting(meetingUrl, adminuser = {}, asGuest = true, recipients=[]) {
  // Set currentMeetingId from environment variable (passed by parent process)
  currentMeetingId = process.env.MEETING_ID;
  
  console.log(`🚀 [meetBot-${currentMeetingId}] Joining meeting: ${meetingUrl}`);

  // Normalize admin user input
  if (adminuser) {
    if (typeof adminuser === "object") {
      adminUserEmail = adminuser.email || process.env.USER_EMAIL || null;
      adminUserName = adminuser.name || adminuser.email?.split('@')[0] || process.env.USER_NAME || null;
    } else if (typeof adminuser === "string") {
      adminUserEmail = adminuser;
      adminUserName = process.env.USER_NAME || null;
    }
  } else {
    adminUserEmail = process.env.USER_EMAIL || null;
    adminUserName = process.env.USER_NAME || null;
  }

  console.log(`👤 [meetBot-${currentMeetingId}] Admin: ${adminUserEmail}, Name: ${adminUserName}`);

  await ensureAuthSession(meetingUrl, asGuest);
  await page.waitForLoadState('networkidle');

  const guestName = "Stormee.Ai";

  if (asGuest) {
    try {
      await pauseAudio();
      const camButton = await page.locator('[aria-label*="camera"]').first();
      if (await camButton.count() > 0) {
        await camButton.click();
        console.log(`📹 [meetBot-${currentMeetingId}] Camera paused.`);
      }
    } catch (error) {
      console.error(`⚠️ [meetBot-${currentMeetingId}] Error pausing media in preview:`, error);
    }

    const nameInput = page.locator('input[aria-label="Your name"], input[placeholder="Your name"]');
    await nameInput.waitFor({ timeout: 10000 }).catch(() => console.log(`⚠️ [meetBot-${currentMeetingId}] Name input not found`));

    if (await nameInput.count() > 0) {
      await nameInput.fill(guestName);
      console.log(`📝 [meetBot-${currentMeetingId}] Entered guest name: ${guestName}`);
    }

    const askToJoinButton = page.locator('[jsname="UywwFc-RLmnJb"], button:has(span:has-text("Ask to join"))');
    await askToJoinButton.waitFor({ timeout: 10000 });
    await askToJoinButton.click();
    console.log(`🚀 [meetBot-${currentMeetingId}] Clicked 'Ask to join'`);
  } else {
    try {
      await pauseAudio();
      const camButton = await page.locator('[aria-label*="camera"]').first();
      if (await camButton.count() > 0) {
        await camButton.click();
        console.log(`📹 [meetBot-${currentMeetingId}] Camera paused.`);
      }
    } catch (error) {
      console.error(`⚠️ [meetBot-${currentMeetingId}] Error pausing media in preview:`, error);
    }

    const joinNowButton = page.locator('button:has-text("Join now")');
    await joinNowButton.waitFor({ timeout: 10000 });
    await joinNowButton.click();
    console.log(`🚀 [meetBot-${currentMeetingId}] Clicked 'Join now'`);
  }

  await page.waitForSelector('button[aria-label*="microphone"]', { timeout: 60000 });

  if (await isMicOn()) {
    await pauseAudio();
  } else {
    console.log(`✅ [meetBot-${currentMeetingId}] Mic already off.`);
  }

  // Auto-start recording and project creation
  console.log(`🎬 [meetBot-${currentMeetingId}] Auto-initializing project and recording...`);
  
  try {
    const creatingProjectResponse = await createProject({
      user: adminUserEmail ?? process.env.USER_EMAIL,
      description: "",
      user_name: adminUserName ?? process.env.USER_NAME,
      name: currentMeetingId
    });

    if (creatingProjectResponse.project_id) {
      projectId = creatingProjectResponse.project_id;
      console.log(`✅ [meetBot-${currentMeetingId}] Successfully created project folder. ProjectID: ${projectId}`);

      // Add admin as recipient
      // if (adminUserEmail) {
      //   addRecipient(adminUserEmail);
      // }

      if (!Array.isArray(recipients)) {
        recipients = [];
      }
      
      addRecipient(recipients);

      console.log("=== MEETING RECIPIENTS ===");
      getRecipients();

      await startAudioRecording(currentMeetingId);
      await startChatScraping();
      
      console.log(`✅ [meetBot-${currentMeetingId}] Auto-initialization complete`);
    } else {
      console.log(`❌ [meetBot-${currentMeetingId}] Failed to initiate folder creation`);
    }
  } catch (error) {
    console.error(`❌ [meetBot-${currentMeetingId}] Error during auto-initialization:`, error);
  }

  if (page) {
    participantCount = await getParticipantCount();
    startParticipantMonitoring();
    console.log(`👥 [meetBot-${currentMeetingId}] Total participant count: ${participantCount}`);
  }
}

async function startCaptions() {
  console.log(`📝 [meetBot-${currentMeetingId}] Starting captions...`);
  captionsSegments = [];
  scrapingActive = true;
  await turnCaptionsOn(page);
  await scrapeCaptions(page);
  console.log(`🟢 [meetBot-${currentMeetingId}] Caption scraping started.`);
}

async function stopCaptions() {
  console.log(`📝 [meetBot-${currentMeetingId}] Stopping captions...`);
  scrapingActive = false;
  console.log(`🔴 [meetBot-${currentMeetingId}] Caption scraping stopped.`);
  return captionsSegments;
}

async function scrapeCaptions(page) {
  const captionSelector = '[data-testid="caption-text"], .captions-text, .closed-captions-text';

  while (scrapingActive) {
    try {
      const captionElements = await page.locator(captionSelector).all();

      for (const element of captionElements) {
        const text = await element.textContent();
        if (text && text.trim()) {
          captionsSegments.push({
            text: text.trim(),
            timestamp: new Date().toISOString(),
          });
        }
      }

      await page.waitForTimeout(1000);
    } catch (error) {
      console.error(`❌ [meetBot-${currentMeetingId}] Error scraping captions:`, error);
      await page.waitForTimeout(5000);
    }
  }
}

async function turnCaptionsOn(page) {
  try {
    const captionsButton = await page
      .locator('[aria-label*="caption"], button:has-text("Turn on captions")')
      .first();
    if ((await captionsButton.count()) > 0) {
      await captionsButton.click();
      console.log(`📝 [meetBot-${currentMeetingId}] Captions enabled.`);
    }
  } catch (error) {
    console.error(`❌ [meetBot-${currentMeetingId}] Error enabling captions:`, error);
  }
}

async function startAudioRecording(meetingId) {
  if (!page) {
    console.error(`❌ [meetBot-${currentMeetingId}] No meeting page available. Join a meeting first.`);
    return;
  }

  const targetMeetingId = meetingId || currentMeetingId;
  
  if (!targetMeetingId) {
    console.error(`❌ [meetBot-${currentMeetingId}] No meetingId provided or set`);
    return;
  }

  currentMeetingId = targetMeetingId;
  audioChunks[targetMeetingId] = audioChunks[targetMeetingId] || [];

  console.log(`🎙️ [meetBot-${currentMeetingId}] Starting full meeting audio recording...`);

  // Initialize WebSocket connection
  if (!socket || !socket.connected) {
    const backendURL = process.env.BACKEND_URL ?? "http://localhost:8080";
    socket = io(backendURL);
    socket.on("connect", () =>
      console.log(`✅ [meetBot-${currentMeetingId}] Connected to WebSocket server for audio streaming.`)
    );
    socket.on("disconnect", () =>
      console.log(`🔌 [meetBot-${currentMeetingId}] Disconnected from WebSocket server.`)
    );
    socket.on("error", (error) => console.error(`❌ [meetBot-${currentMeetingId}] WebSocket error:`, error));
  }

  // Check if sendAudioChunkToNode is already exposed
  const isFunctionExposed = await page.evaluate(() => {
    return typeof window.sendAudioChunkToNode === "function";
  });

  if (!isFunctionExposed) {
    await page.exposeFunction("sendAudioChunkToNode", (chunk) => {
      console.log(
        `📥 [meetBot-${currentMeetingId}] Received audio chunk: ${chunk.chunkId}, size: ${chunk.audioBlob.length} bytes`
      );
      if (socket && socket.connected) {
        socket.emit("audioChunk", chunk, (response) => {
          if (response && response.success) {
            console.log(`✅ [meetBot-${currentMeetingId}] Server acknowledged chunk: ${chunk.chunkId}`);
          } else {
            console.error(`❌ [meetBot-${currentMeetingId}] Server failed to acknowledge chunk: ${chunk.chunkId}`);
          }
        });
      } else {
        console.warn(`⚠️ [meetBot-${currentMeetingId}] Socket not connected; chunk ${chunk.chunkId} not sent.`);
      }
      audioChunks[chunk.meetingId].push(chunk);
    });
    console.log(`✅ [meetBot-${currentMeetingId}] Exposed sendAudioChunkToNode function.`);
  } else {
    console.log(`ℹ️ [meetBot-${currentMeetingId}] sendAudioChunkToNode already exposed.`);
  }

  // Start recording in browser
  await page.evaluate(async (meetingId) => {
    try {
      if (window.mediaRecorder && window.mediaRecorder.state !== "inactive") {
        window.mediaRecorder.stop();
        console.log("🛑 Stopped existing MediaRecorder.");
      }

      const audioCtx = new AudioContext();
      const destination = audioCtx.createMediaStreamDestination();

      if (window.remoteAudioStreams && window.remoteAudioStreams.length > 0) {
        window.remoteAudioStreams.forEach((stream) => {
          const remoteSource = audioCtx.createMediaStreamSource(stream);
          remoteSource.connect(destination);
          console.log("Connected remote stream to mixer.");
        });
      } else {
        console.warn("⚠️ No remote audio streams captured yet.");
      }

      window.addEventListener("remoteStreamAdded", (event) => {
        const stream = event.detail;
        const remoteSource = audioCtx.createMediaStreamSource(stream);
        remoteSource.connect(destination);
        console.log("Connected new remote stream to mixer.");
      });

      const mixedStream = destination.stream;
      const mediaRecorder = new MediaRecorder(mixedStream, {
        mimeType: "audio/webm; codecs=opus",
      });

      window.mediaRecorder = mediaRecorder;

      let chunkCounter = 0;

      mediaRecorder.ondataavailable = async (event) => {
        console.log(`📤 Browser: Audio data available, size: ${event.data.size} bytes`);
        if (event.data.size > 0) {
          const chunkId = `${meetingId}-${chunkCounter++}`;
          const timestamp = new Date().toISOString();
          const arrayBuffer = await event.data.arrayBuffer();
          const audioBlob = Array.from(new Uint8Array(arrayBuffer));
          window.sendAudioChunkToNode({
            meetingId,
            chunkId,
            timestamp,
            audioBlob,
          });
        }
      };

      mediaRecorder.onerror = (event) => console.error("MediaRecorder error:", event.error);
      mediaRecorder.onstop = () => console.log("MediaRecorder stopped");

      mediaRecorder.start(60000); // 1-minute chunks
      console.log("🎤 MediaRecorder started with 1-minute chunks");
    } catch (error) {
      console.error("❌ Error starting audio recording:", error);
    }
  }, targetMeetingId);

  console.log(`✅ [meetBot-${currentMeetingId}] Full audio recording started successfully.`);
}

async function saveAudio(meetingId) {
  if (!audioChunks[meetingId] || audioChunks[meetingId].length === 0) {
    console.log(`⚠️ [meetBot-${meetingId}] No audio chunks to save.`);
    return;
  }

  console.log(`💾 [meetBot-${meetingId}] Saving audio...`);

  const sortedChunks = audioChunks[meetingId].sort((a, b) => {
    const aNum = parseInt(a.chunkId.split('-').pop());
    const bNum = parseInt(b.chunkId.split('-').pop());
    return aNum - bNum;
  });

  const buffers = sortedChunks.map(chunk => Buffer.from(chunk.audioBlob));
  const concatenated = Buffer.concat(buffers);

  const webmPath = `${meetingId}.webm`;
  fs.writeFileSync(webmPath, concatenated);
  console.log(`✅ [meetBot-${meetingId}] Saved WebM: ${webmPath}, size: ${concatenated.length} bytes`);

  const wavPath = `${meetingId}.wav`;
  try {
    await execAsync(`ffmpeg -i ${webmPath} -acodec pcm_s16le -ar 48000 -ac 2 ${wavPath}`);
    console.log(`✅ [meetBot-${meetingId}] Converted to WAV: ${wavPath}`);
    fs.unlinkSync(webmPath);
    return wavPath;
  } catch (error) {
    console.error(`❌ [meetBot-${meetingId}] Error converting to WAV:`, error);
    try { fs.unlinkSync(webmPath); } catch {}
    return null;
  }
}

async function uploadAudioFile(meetingId, wavPath) {
  if (!wavPath || !fs.existsSync(wavPath)) {
    console.error(`❌ [meetBot-${meetingId}] WAV file not found: ${wavPath}`);
    return false;
  }

  console.log(`📤 [meetBot-${meetingId}] Uploading WAV...`);

  const maxRetries = 3;
  let uploaded = false;

  for (let i = 0; i < maxRetries; i++) {
    try {
      const uploadResponse = await uploadFile({
        projectID: projectId,
        files: wavPath,
      });

      console.log(`✅ [meetBot-${meetingId}] Uploaded WAV: ${wavPath}`);
      uploaded = true;

      try {
        if (uploadResponse) {
          console.log(`📁 [meetBot-${meetingId}] Generating meeting mode artifact...`, uploadResponse);
          const artifact = await generateMeetingModeArtifact({
            audioName: `${meetingId}.wav`,
            projectId: projectId,
            displayName: `Meeting Artifact - ${meetingId}`,
            userEmail: adminUserEmail ?? process.env.USER_EMAIL,
            userName: adminUserName ?? process.env.USER_NAME
          });

          try {
            const artifactData = artifact?.artifact_upload_result?.artifact_data?.artifactData;
            console.log(`📊 [meetBot-${meetingId}] Artifact generated:`, artifactData);

            await createArtifactAndSendEmail(artifact, projectId, getRecipients(meetingId));
            console.log(`📧 [meetBot-${meetingId}] Emails sent to recipients`);
          } catch (err) {
            console.log(`❌ [meetBot-${meetingId}] Failed to send email:`, err);
          }
        }
      } catch (err) {
        console.log(`❌ [meetBot-${meetingId}] Failed to create artifact:`, err);
      }
      break;
    } catch (err) {
      console.error(`❌ [meetBot-${meetingId}] Upload attempt ${i + 1} failed:`, err.message);
      if (i === maxRetries - 1) {
        console.error(`❌ [meetBot-${meetingId}] Final upload failed`);
      } else {
        await new Promise(r => setTimeout(r, 2000 * (i + 1)));
      }
    }
  }

  if (uploaded) {
    try {
      fs.unlinkSync(wavPath);
      console.log(`🗑️ [meetBot-${meetingId}] Cleaned up local WAV: ${wavPath}`);
    } catch (err) {
      console.warn(`⚠️ [meetBot-${meetingId}] Failed to delete WAV:`, err);
    }
  }

  return uploaded;
}

async function stopAudioRecording() {
  if (!page) {
    console.error(`❌ [meetBot-${currentMeetingId}] No meeting page available.`);
    return;
  }

  console.log(`⏹️ [meetBot-${currentMeetingId}] Stopping audio recording...`);

  await page.evaluate(() => {
    if (window.mediaRecorder && window.mediaRecorder.state !== "inactive") {
      window.mediaRecorder.stop();
      console.log("🛑 MediaRecorder stopped");
    }
  });

  if (currentMeetingId) {
    const wavPath = await saveAudio(currentMeetingId);
    if (wavPath && projectId) {
      await uploadAudioFile(currentMeetingId, wavPath);
    }
  }

  if (socket) {
    socket.disconnect();
    socket = null;
    console.log(`🔌 [meetBot-${currentMeetingId}] WebSocket disconnected.`);
  }

  console.log(`✅ [meetBot-${currentMeetingId}] Audio recording stopped successfully.`);
}

async function startChatScraping() {
  console.log(`💬 [meetBot-${currentMeetingId}] Starting chat scraping...`);
  chatSegments = [];
  chatScrapingActive = true;

  const maxRetries = 8;
  const retryDelay = 5000;

  async function attemptChatScraping(attempt = 1) {
    try {
      if (!page) {
        console.error(`❌ [meetBot-${currentMeetingId}] No meeting page available.`);
        chatScrapingActive = false;
        return;
      }

      const chatButton = await page.locator('[aria-label="Show chat"], button:has-text("Chat")').first();
      if ((await chatButton.count()) > 0) {
        await chatButton.click();
        console.log(`💬 [meetBot-${currentMeetingId}] Chat window opened.`);
        
        const chatPanel = await page.locator('.Ge9Kpc, [aria-live="polite"]').first();
        await chatPanel.waitFor({ state: 'visible', timeout: 10000 }).catch(() => {
          console.error(`❌ [meetBot-${currentMeetingId}] Chat panel did not open.`);
          chatScrapingActive = false;
          return;
        });
      } else {
        if (attempt <= maxRetries) {
          console.log(`⚠️ [meetBot-${currentMeetingId}] Chat button not found. Retrying (${attempt}/${maxRetries})...`);
          await new Promise(resolve => setTimeout(resolve, retryDelay));
          return await attemptChatScraping(attempt + 1);
        } else {
          console.error(`❌ [meetBot-${currentMeetingId}] Chat button not found after max retries.`);
          chatScrapingActive = false;
          return;
        }
      }

      const isFunctionExposed = await page.evaluate(() => {
        return typeof window.sendChatMessageToNode === "function";
      });

      if (!isFunctionExposed) {
        await page.exposeFunction("sendChatMessageToNode", async (chatMessage) => {
          chatSegments.push(chatMessage);
          console.log(`💬 [meetBot-${currentMeetingId}] New chat message:`, chatMessage);

          const messageText = chatMessage.text.toLowerCase();
          
          if (messageText.includes("stormee start recording")) {
            if (currentMeetingId && audioChunks[currentMeetingId]) {
              console.log(`ℹ️ [meetBot-${currentMeetingId}] Recording already in progress`);
            } else {
              const meetingId = currentMeetingId || `meeting-${Date.now()}`;
              console.log(`🚀 [meetBot-${currentMeetingId}] Starting recording via chat command...`);
              try {
                await startAudioRecording(meetingId);
              } catch (error) {
                console.error(`❌ [meetBot-${currentMeetingId}] Error starting recording:`, error);
              }
            }
          } else if (messageText.includes("stormee start caption recording")) {
            if (scrapingActive) {
              console.log(`ℹ️ [meetBot-${currentMeetingId}] Caption recording already in progress`);
            } else {
              console.log(`🚀 [meetBot-${currentMeetingId}] Starting captions via chat command...`);
              try {
                await startCaptions();
              } catch (error) {
                console.error(`❌ [meetBot-${currentMeetingId}] Error starting captions:`, error);
              }
            }
          } else if (messageText.includes("stormee stop recording")) {
            if (!currentMeetingId || !audioChunks[currentMeetingId]) {
              console.log(`ℹ️ [meetBot-${currentMeetingId}] No recording in progress`);
            } else {
              try {
                await stopAudioRecording();
              } catch (err) {
                console.error(`❌ [meetBot-${currentMeetingId}] Error stopping recording:`, err);
              }
            }
          } else if (messageText.toLowerCase().startsWith("stormee add email")) {
            if (!currentMeetingId) {
              console.log(`ℹ️ [meetBot-${currentMeetingId}] No active meeting for adding recipient`);
              return;
            }
            try {
              const email = messageText.split("stormee add email")[1].trim();
              if (!email || !email.includes("@")) {
                console.log(`❌ [meetBot-${currentMeetingId}] Invalid email format`);
                return;
              }
              addRecipient(email, currentMeetingId);
              console.log(`✅ [meetBot-${currentMeetingId}] Added recipient: ${email}`);
            } catch (err) {
              console.error(`❌ [meetBot-${currentMeetingId}] Error adding recipient:`, err);
            }
          }
        });
        console.log(`✅ [meetBot-${currentMeetingId}] Exposed sendChatMessageToNode function.`);
      } else {
        console.log(`ℹ️ [meetBot-${currentMeetingId}] sendChatMessageToNode already exposed.`);
      }

      await page.evaluate(() => {
        const chatContainer = document.querySelector('.Ge9Kpc, [aria-live="polite"]');
        if (!chatContainer) {
          console.error("❌ Chat container not found.");
          return;
        }

        const processedMessageIds = new Set();

        const observer = new MutationObserver((mutations) => {
          mutations.forEach((mutation) => {
            if (mutation.addedNodes.length) {
              mutation.addedNodes.forEach((node) => {
                if (node.nodeType === Node.ELEMENT_NODE && node.matches('div.RLrADb')) {
                  const messageId = node.getAttribute('data-message-id') || 'unknown';
                  if (processedMessageIds.has(messageId)) return;
                  processedMessageIds.add(messageId);

                  const senderElement = node.querySelector('div[class="poVWob"] > div');
                  const timestampElement = node.querySelector('.MuzmKe');
                  const textElement = node.querySelector('div[jsname="dTKtvb"] > div');
                  
                  const chatMessage = {
                    sender: senderElement ? senderElement.textContent.trim() : 'Unknown',
                    text: textElement ? textElement.textContent.trim() : '',
                    timestamp: timestampElement ? timestampElement.textContent.trim() : new Date().toISOString(),
                    messageId: messageId,
                  };

                  if (chatMessage.text) {
                    window.sendChatMessageToNode(chatMessage);
                  }
                }
              });
            }
          });
        });

        observer.observe(chatContainer, {
          childList: true,
          subtree: true,
        });

        // Process existing messages
        const existingMessages = chatContainer.querySelectorAll('div.RLrADb');
        existingMessages.forEach((node) => {
          const messageId = node.getAttribute('data-message-id') || 'unknown';
          if (processedMessageIds.has(messageId)) return;
          processedMessageIds.add(messageId);

          const senderElement = node.querySelector('.poVWob');
          const timestampElement = node.querySelector('.MuzmKe');
          const textElement = node.querySelector('div[jsname="dTKtvb"] > div');

          const chatMessage = {
            sender: senderElement ? senderElement.textContent.trim() : 'Unknown',
            text: textElement ? textElement.textContent.trim() : '',
            timestamp: timestampElement ? timestampElement.textContent.trim() : new Date().toISOString(),
            messageId: messageId,
          };

          if (chatMessage.text) {
            window.sendChatMessageToNode(chatMessage);
          }
        });

        console.log("🟢 Mutation observer started for chat scraping.");
      });

      console.log(`🟢 [meetBot-${currentMeetingId}] Chat scraping started.`);
    } catch (error) {
      console.error(`❌ [meetBot-${currentMeetingId}] Error starting chat scraping:`, error);
      chatScrapingActive = false;
    }
  }

  await attemptChatScraping();
}

async function stopChatScraping() {
  console.log(`💬 [meetBot-${currentMeetingId}] Stopping chat scraping...`);
  chatScrapingActive = false;
  
  await page.evaluate(() => {
    const chatContainer = document.querySelector('.Ge9Kpc, [aria-live="polite"]');
    if (chatContainer) {
      const observer = new MutationObserver(() => {});
      observer.disconnect();
      console.log("🛑 Mutation observer stopped.");
    }
  });
  
  console.log(`🔴 [meetBot-${currentMeetingId}] Chat scraping stopped.`);
  return chatSegments;
}

async function getParticipantCount() {
  if (!page) {
    console.error(`❌ [meetBot-${currentMeetingId}] No meeting page available.`);
    return 0;
  }

  const maxRetries = 8;
  const retryDelay = 5000;

  async function attemptParticipantCount(attempt = 1) {
    try {
      await page.waitForSelector('[data-participant-id]', { timeout: 10000 });
      const participantElements = await page.$$('[data-participant-id]');
      const count = participantElements.length;
      console.log(`👥 [meetBot-${currentMeetingId}] Participant count: ${count}`);
      return count;
    } catch (error) {
      if (attempt <= maxRetries) {
        console.log(`⚠️ [meetBot-${currentMeetingId}] Participants not found. Retrying (${attempt}/${maxRetries})...`);
        await new Promise(resolve => setTimeout(resolve, retryDelay));
        return await attemptParticipantCount(attempt + 1);
      } else {
        console.error(`❌ [meetBot-${currentMeetingId}] Participants not found after max retries.`);
        return 0;
      }
    }
  }

  return await attemptParticipantCount();
}

async function leaveMeeting() {
  if (!page) {
    console.error(`❌ [meetBot-${currentMeetingId}] No meeting page available.`);
    return;
  }

  console.log(`🚪 [meetBot-${currentMeetingId}] Leaving meeting...`);

  try {
    await stopChatScraping();
    
    if (currentMeetingId && audioChunks[currentMeetingId]?.length > 0) {
      await stopAudioRecording();
    }
    
    await stopCaptions();
    stopParticipantMonitoring();

    const leaveButton = await page.locator('[aria-label="Leave call"], button:has-text("Leave call")').first();
    if (await leaveButton.count() > 0) {
      await leaveButton.click();
      console.log(`🚀 [meetBot-${currentMeetingId}] Clicked 'Leave call' button.`);
    } else {
      console.warn(`⚠️ [meetBot-${currentMeetingId}] Leave call button not found.`);
    }

    if (context) {
      await context.close();
      console.log(`🔒 [meetBot-${currentMeetingId}] Context closed.`);
    }
    if (browser) {
      await browser.close();
      console.log(`🔒 [meetBot-${currentMeetingId}] Browser closed.`);
    }

    page = null;
    context = null;
    browser = null;
    participantCount = 0;

    console.log(`✅ [meetBot-${currentMeetingId}] Successfully left the meeting.`);
  } catch (error) {
    console.error(`❌ [meetBot-${currentMeetingId}] Error leaving meeting:`, error);
  }
}

function startParticipantMonitoring() {
  if (participantMonitorInterval) {
    console.log(`ℹ️ [meetBot-${currentMeetingId}] Participant monitoring already active.`);
    return;
  }

  console.log(`🟢 [meetBot-${currentMeetingId}] Starting participant monitoring...`);
  let lastCount = participantCount;

  participantMonitorInterval = setInterval(async () => {
    if (!page || !chatScrapingActive) {
      console.log(`⚠️ [meetBot-${currentMeetingId}] Stopping monitoring: page unavailable.`);
      stopParticipantMonitoring();
      return;
    }

    try {
      const newCount = await getParticipantCount();
      if (newCount !== lastCount) {
        console.log(`🔄 [meetBot-${currentMeetingId}] Participant count changed: ${lastCount} → ${newCount}`);
        participantCount = newCount;
      }

      lastCount = newCount;

      if (newCount === 1) {
        console.log(`⚠️ [meetBot-${currentMeetingId}] Only bot remains. Exiting...`);
        await leaveMeeting();
      }
    } catch (error) {
      console.error(`❌ [meetBot-${currentMeetingId}] Error during participant monitoring:`, error);
    }
  }, 1000 * 60 * 5);
}

function stopParticipantMonitoring() {
  if (participantMonitorInterval) {
    clearInterval(participantMonitorInterval);
    participantMonitorInterval = null;
    console.log(`🔴 [meetBot-${currentMeetingId}] Participant monitoring stopped.`);
  }
}

// Can add email or array of emails as recipients for meeting artifacts
function addRecipient(email, meetingId) {
  const targetMeetingId = meetingId || currentMeetingId;
  
  if (!targetMeetingId) {
    console.error(`❌ [meetBot] No meetingId provided for addRecipient`);
    return [];
  }

  if (!recipients[targetMeetingId]) {
    recipients[targetMeetingId] = new Set();
  }

  const emails = Array.isArray(email) ? email : [email];
  
  emails.forEach(e => {
    if (e && typeof e === 'string' && e.trim()) {
      recipients[targetMeetingId].add(e.trim());
      console.log(`✅ [meetBot-${targetMeetingId}] Added recipient: ${e.trim()}`);
    } else {
      console.warn(`⚠️ [meetBot-${targetMeetingId}] Invalid email skipped: ${e}`);
    }
  });

  // recipients[targetMeetingId].add(email);
  console.log(`✅ [meetBot-${targetMeetingId}] Added recipient: ${email}`);

  return Array.from(recipients[targetMeetingId]);
}

function removeRecipient(email, meetingId) {
  const targetMeetingId = meetingId || currentMeetingId;

  if (recipients[targetMeetingId]) {
    recipients[targetMeetingId].delete(email);
    console.log(`✅ [meetBot-${targetMeetingId}] Removed recipient: ${email}`);
  }

  return Array.from(recipients[targetMeetingId] || []);
}

function getRecipients(meetingId) {
  const targetMeetingId = meetingId || currentMeetingId;
  const users = Array.from(recipients[targetMeetingId] || []);

  console.log(`📧 [meetBot-${targetMeetingId}] Recipients:`, users);
  return users;
}

export {
  startCaptions,
  stopCaptions,
  playAudio,
  performGoogleLogin,
  joinMeeting,
  pauseAudio,
  startAudioRecording,
  stopAudioRecording,
  addRecipient,
  removeRecipient,
  getRecipients,
  isMicOn,
  startChatScraping,
  stopChatScraping,
  leaveMeeting
};
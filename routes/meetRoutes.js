import express from "express";
import fs from 'fs';
import path from 'path';
import {google} from 'googleapis';

import {
  loginController,
  startAudioController,
  startCaptionsController,
  stopAudioController,
  stopCaptionsController,
  startRecordingController,
  stopRecordingController,
  getRecordingStatusController,
  startChatScrapingController,
  stopChatScrapingController,
  getAllMeetingsController,
  exitMeeting,
} from "../controllers/meetController.js";

import {
    addRecipientController,
    removeRecipientController,
    getRecipientsController
} from "../controllers/recipientController.js";

import { authenticateWithPlaywright } from '../services/integrations/calendarAPI.js';

const router = express.Router();

// Health check route
const checkingHealth = (req, res) => {
  res.status(200).json({ status: "OK", message: "Service is running" });
};

// Recipient routes
router.get("/recipient/fetch", getRecipientsController);
router.post("/recipient/add", addRecipientController);
router.delete("/recipient/remove", removeRecipientController);

// Existing API routes for Google Meet functionality
router.post("/start", startCaptionsController);
router.post("/stop", stopCaptionsController);
router.get("/health", checkingHealth);
router.post("/audio", startAudioController);
router.post("/signin", loginController);
router.post("/pauseaudio", stopAudioController);
router.get("/meetings", getAllMeetingsController);

// New API routes for audio recording functionality
router.post("/record/start", startRecordingController);
router.post("/record/stop", stopRecordingController);
router.get("/record/status", getRecordingStatusController);
router.post('/chat/start',startChatScrapingController);
router.get('/chat/stop',stopChatScrapingController);
router.post('/exit',exitMeeting);

// Setup OAuth2 client (you'll need to pass this or create it here)
const oauth2Client = new google.auth.OAuth2(
  process.env.CLIENT_ID,
  process.env.CLIENT_SECRET,
  process.env.REDIRECT_URI
);

oauth2Client.setCredentials({
  access_token: process.env.ACCESS_TOKEN,
  refresh_token: process.env.REFRESH_TOKEN,
});

const calendar = google.calendar({ version: 'v3', auth: oauth2Client });
router.post('/webhook', async (req, res) => {
  console.log('Received webhook notification');
  
  // Extract useful headers
  const channelId = req.headers['x-goog-channel-id'];
  const resourceState = req.headers['x-goog-resource-state']; // 'sync', 'exists', 'not_exists'
  const resourceId = req.headers['x-goog-resource-id'];
  const messageNumber = req.headers['x-goog-message-number'];
  const channelToken = req.headers['x-goog-channel-token'];
  const channelExpiration = req.headers['x-goog-channel-expiration'];
  const resourceUri = req.headers['x-goog-resource-uri'];
  
  console.log('\n=== WEBHOOK DETAILS ===');
  console.log('Channel ID:', channelId);
  console.log('Resource State:', resourceState);
  console.log('Message Number:', messageNumber);
  console.log('Expiration:', channelExpiration);
  console.log('Resource URI:', resourceUri);
  
  // Create a logs directory if it doesn't exist
  const logsDir = path.join(process.cwd(), 'webhook-logs');
  if (!fs.existsSync(logsDir)) {
    fs.mkdirSync(logsDir, { recursive: true });
  }
  
  // Prepare initial webhook data
  const webhookData = {
    timestamp: new Date().toISOString(),
    usefulHeaders: {
      channelId,
      resourceState,
      resourceId,
      messageNumber,
      channelToken,
      channelExpiration,
      resourceUri
    },
    headers: req.headers,
    body: req.body,
    query: req.query,
    method: req.method,
    url: req.url,
    ip: req.ip,
  };
  
  // Acknowledge receipt immediately (important!)
  res.status(200).send('OK');
  
  // Handle different resource states
  if (resourceState === 'sync') {
    console.log('This is a sync message - watch channel successfully established');
    webhookData.note = 'Sync message - watch channel established';
  } else if (resourceState === 'exists') {
    console.log('Calendar modified! Authenticating and fetching event...\n');
    
    try {
      // Authenticate using the automated Playwright method
      console.log('Authenticating with Google...');
      const { oauth2Client } = await authenticateWithPlaywright();
      
      // Create calendar client
      const calendar = google.calendar({ version: 'v3', auth: oauth2Client });
      console.log('Calendar client created successfully');
      
      // Fetch the most recently updated event (regardless of when it starts)
      const updatedMin = new Date(Date.now() - 30000).toISOString(); // Last 30 seconds to be safe
      
      const result = await calendar.events.list({
        calendarId: 'primary',
        updatedMin: updatedMin,
        maxResults: 1, // Only get the most recently updated one
        singleEvents: true,
        orderBy: 'updated', // Sort by update time (most recent first)
      });

      const events = result.data.items;
      
      if (events && events.length > 0) {
        const event = events[0]; // Get the single most recently updated event
        console.log(`Found the most recently updated event: ${event.summary}`);
        
        // Check if event is in the past
        const eventStartTime = new Date(event.start?.dateTime || event.start?.date);
        const now = new Date();
        
        if (eventStartTime < now) {
          console.log('Event is in the past. Skipping...');
          webhookData.skipped = true;
          webhookData.skipReason = 'Event is in the past';
          webhookData.eventSummary = event.summary;
          webhookData.eventStartTime = eventStartTime.toISOString();
          return; // Exit early
        }
        
        // Check if it's a Google Meet event
        const isGoogleMeet = event.conferenceData?.entryPoints?.some(ep => ep.entryPointType === 'video') 
                           || event.hangoutLink;
        
        if (!isGoogleMeet) {
          console.log('Event is not a Google Meet. Skipping...');
          webhookData.skipped = true;
          webhookData.skipReason = 'Not a Google Meet event';
          webhookData.eventSummary = event.summary;
          webhookData.eventStartTime = eventStartTime.toISOString();
          return; // Exit early
        }
        
        console.log('Event is a future Google Meet! Processing...');
        
        // Get full event details
        const eventDetails = await calendar.events.get({
          calendarId: 'primary',
          eventId: event.id,
        });
        
        const fullEvent = eventDetails.data;
        
        // Extract event information
        const eventInfo = {
          eventId: fullEvent.id,
          summary: fullEvent.summary,
          description: fullEvent.description,
          isGoogleMeet,
          meetLink: fullEvent.hangoutLink || null,
          created: fullEvent.created,
          updated: fullEvent.updated,
          startTime: fullEvent.start?.dateTime || fullEvent.start?.date,
          endTime: fullEvent.end?.dateTime || fullEvent.end?.date,
          organizer: {
            email: fullEvent.organizer?.email,
            displayName: fullEvent.organizer?.displayName,
            self: fullEvent.organizer?.self
          },
          attendees: [],
          status: fullEvent.status,
          htmlLink: fullEvent.htmlLink
        };
        
        // Extract attendees/recipients
        if (fullEvent.attendees && fullEvent.attendees.length > 0) {
          fullEvent.attendees.forEach(attendee => {
            eventInfo.attendees.push({
              email: attendee.email,
              displayName: attendee.displayName || null,
              responseStatus: attendee.responseStatus, // needsAction, declined, tentative, accepted
              optional: attendee.optional || false,
              organizer: attendee.organizer || false,
              self: attendee.self || false
            });
          });
        }
        
        // Log event details
        console.log(`${new Date()}`)
        console.log('\n === EVENT DETAILS ===');
        console.log('Event ID:', eventInfo.eventId);
        console.log('Title:', eventInfo.summary);
        console.log('Start Time:', eventInfo.startTime);
        console.log('End Time:', eventInfo.endTime);
        console.log('Is Google Meet:', eventInfo.isGoogleMeet);
        if (eventInfo.meetLink) {
          console.log('Meet Link:', eventInfo.meetLink);
        }
        console.log('\nORGANIZER:');
        console.log('  Email:', eventInfo.organizer.email);
        console.log('  Name:', eventInfo.organizer.displayName || 'N/A');
        
        if (eventInfo.attendees.length > 0) {
          console.log('\nATTENDEES:');
          eventInfo.attendees.forEach((attendee, index) => {
            console.log(`  ${index + 1}. ${attendee.email}`);
            console.log(`     Name: ${attendee.displayName || 'N/A'}`);
            console.log(`     Status: ${attendee.responseStatus}`);
            console.log(`     Optional: ${attendee.optional}`);
          });
        } else {
          console.log('\nNo attendees');
        }
        
        webhookData.event = eventInfo; // Single event object
      } else {
        console.log('No recently updated event found');
        webhookData.event = null;
      }
      
    } catch (error) {
      console.error('Error fetching calendar event:', error.message);
      webhookData.error = {
        message: error.message,
        stack: error.stack
      };
    }
  }
  
  // Write to file
  const filepath = path.join(logsDir, 'webhooks.json');
  
  try {
    let existingData = [];
    
    // Read existing file if it exists
    if (fs.existsSync(filepath)) {
      const fileContent = fs.readFileSync(filepath, 'utf-8');
      existingData = JSON.parse(fileContent);
    }
    
    // Append new webhook data
    existingData.push(webhookData);
    
    // Write back to file
    fs.writeFileSync(filepath, JSON.stringify(existingData, null, 2));
    console.log(`\nWebhook data written to: ${filepath}`);
    console.log(`Total webhooks logged: ${existingData.length}`);
  } catch (error) {
    console.error('Error writing webhook to file:', error);
  }
});

export default router;

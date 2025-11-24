import process from 'node:process';
import {google} from 'googleapis';
import crypto from 'node:crypto';
import { chromium } from 'playwright';
import { SCOPES, WEBHOOK_URL } from '../../constants/calender.constants.js'; 

/**
 * Authenticate using Playwright
 */
async function authenticateWithPlaywright() {
  const credentials = {
    web: {
      client_id: process.env.GOOGLE_CLIENT_ID,
      project_id: "proposal-auto-ai-internal",
      auth_uri: "https://accounts.google.com/o/oauth2/auth",
      token_uri: "https://oauth2.googleapis.com/token",
      auth_provider_x509_cert_url: "https://www.googleapis.com/oauth2/v1/certs",
      client_secret: process.env.GOOGLE_CLIENT_SECRET,
      redirect_uris: [
        "https://dev.appmod.ai",
        "https://appmod.ai",
        "http://localhost:8080",
        "http://localhost",
      ],
      javascript_origins: [
        "https://dev.appmod.ai",
        "https://appmod.ai",
        "http://localhost:8080",
        "http://localhost",
      ],
    },
  };
  const { client_secret, client_id, redirect_uris } = credentials.web;

  // Create OAuth2 client
  const oauth2Client = new google.auth.OAuth2(
    client_id,
    client_secret,
    redirect_uris[0]
  );

  // Generate the consent URL
  const authUrl = oauth2Client.generateAuthUrl({
    access_type: 'offline',
    scope: SCOPES,
    prompt: 'consent'
  });

  console.log('\n=== OPENING OAUTH CONSENT IN PLAYWRIGHT ===\n');
  console.log('URL:', authUrl);
  console.log('\nPlease complete the authentication manually in the browser...\n');

  // Launch browser with Playwright
  const browser = await chromium.launch({
    headless: true,
    args: [
      "--disable-blink-features=AutomationControlled",
      "--start-maximized",
      "--use-fake-device-for-media-stream",
      "--use-fake-ui-for-media-stream",
    ],
    // slowMo: 100 // Slow down operations for better visibility
  });
  const context = await browser.newContext();
  const page = await context.newPage();

  // Navigate to the consent URL
  await page.goto(authUrl);

  // Wait for the redirect with the authorization code
  // This will wait until URL contains 'code=' parameter
  try {
    const email = process.env.GOOGLE_ACCOUNT_USER;
    const emailInput = page.locator('input[type="email"]');
    await emailInput.waitFor({ timeout: 10000 });
    await emailInput.fill(email);
    await page.locator('button:has-text("Next")').click();

    console.log(`Clicked Next after email`);

    const password = process.env.GOOGLE_ACCOUNT_PASSWORD;
    const passwordInput = page.locator('input[type="password"]:visible');
    passwordInput.waitFor({ timeout: 10000 });
    await passwordInput.fill(password);
    await page.locator('button:has-text("Next")').click();

    console.log(`Clicked Next after password`);

    const allowbutton = page.locator('button:has-text("Allow")');
    await allowbutton.waitFor({ timeout: 20000 });
    await allowbutton.click();
    console.log(`Clicked Allow for permissions`);

    console.log(`Entered email: ${email}`);

    await page.waitForURL(/code=/, { timeout: 300000 }); // 5 minutes timeout

    // Extract the authorization code from the URL
    const url = new URL(page.url());
    const code = url.searchParams.get('code');

    console.log('\n=== AUTHORIZATION CODE RECEIVED ===\n');
    console.log('Code:', code);

    // Close the browser
    await browser.close();

    // Exchange code for tokens
    const { tokens } = await oauth2Client.getToken(code);
    oauth2Client.setCredentials(tokens);

    console.log('\n=== TOKENS RECEIVED ===\n');
    console.log(JSON.stringify(tokens, null, 2));

    return { oauth2Client, tokens };
  } catch (error) {
    console.error('Error during authentication:', error.message);
    await browser.close();
    throw error;
  }
}

// Replace authenticateWithPlaywright() with this:
async function authenticateWithRefreshToken() {
  const oauth2Client = new google.auth.OAuth2(
    process.env.GOOGLE_CLIENT_ID,
    process.env.GOOGLE_CLIENT_SECRET,
    "https://dev.appmod.ai"
  );

  oauth2Client.setCredentials({
    refresh_token: process.env.GOOGLE_AUTH_REFRESH_TOKEN,
  });

  console.log("Authenticated using refresh token.", oauth2Client);

  return { oauth2Client };
}

/**
 * Sets up a watch on the primary calendar to receive notifications
 */
async function setupCalendarWatch(calendar) {
  try {
    // Generate a unique channel ID and token
    const channelId = crypto.randomUUID();
    const token = crypto.randomBytes(32).toString('hex');

    console.log('\n=== SETTING UP CALENDAR WATCH ===\n');
    console.log('Channel ID:', channelId);
    console.log('Token:', token);
    console.log('Webhook URL:', WEBHOOK_URL);
    console.log('');

    const watchResponse = await calendar.events.watch({
      calendarId: 'primary',
      requestBody: {
        id: channelId, // Unique channel identifier
        type: 'web_hook',
        address: WEBHOOK_URL, // Your webhook endpoint
        token: token, // Optional token for verification
        expiration: Date.now() + (7 * 24 * 60 * 60 * 1000), // 7 days from now (max allowed)
      },
    });

    console.log('Watch successfully set up!');
    console.log('Watch details:', JSON.stringify(watchResponse.data, null, 2));
    console.log('\nYour webhook will receive notifications for calendar changes.');
    console.log('Expiration:', new Date(parseInt(watchResponse.data.expiration)).toISOString());

    return watchResponse.data;
  } catch (error) {
    console.error('Error setting up calendar watch:', error.message);
    console.error('Full error:', error);
    throw error;
  }
}

/**
 * Stops a watch channel
 */
async function stopCalendarWatch(calendar, channelId, resourceId) {
  try {
    console.log('\n=== STOPPING CALENDAR WATCH ===\n');

    await calendar.channels.stop({
      requestBody: {
        id: channelId,
        resourceId: resourceId,
      },
    });

    console.log('Watch successfully stopped!');
  } catch (error) {
    console.error('Error stopping calendar watch:', error.message);
    console.error('Full error:', error);
  }
}

/**
 * Lists the next 10 events on the user's primary calendar.
 */
async function listEvents() {
  // Authenticate with Google using Playwright
  const { oauth2Client, tokens } = await authenticateWithPlaywright();

  console.log('\n\n\t\t-----------------------------\n\n');

  // Create a new Calendar API client with the oauth2Client
  const calendar = google.calendar({ version: 'v3', auth: oauth2Client });

  try {
    // Set up calendar watch (COMMENTED OUT)
    // const watchData = await setupCalendarWatch(calendar);
    // console.log('Watch Data:', watchData);

    console.log('\n\n\t\t-----------------------------\n\n');

    // Get the list of events
    const result = await calendar.events.list({
      calendarId: 'primary',
      timeMin: new Date().toISOString(),
      maxResults: 10,
      singleEvents: true,
      orderBy: 'startTime',
    });

    const events = result.data.items;

    if (!events || events.length === 0) {
      console.log('No upcoming events found.');
      return;
    }

    // Find the first Google Meet event
    let meetEvent = null;
    for (const event of events) {
      // Check if event has a Google Meet link
      if (event.conferenceData?.entryPoints?.some(ep => ep.entryPointType === 'video')) {
        meetEvent = event;
        break;
      }
      // Alternative check: look for hangoutLink or meet.google.com in the event
      if (event.hangoutLink || event.htmlLink?.includes('meet.google.com')) {
        meetEvent = event;
        break;
      }
    }

    if (!meetEvent) {
      console.log('No Google Meet events found in the upcoming 10 events.');
      return;
    }

    console.log('Found Google Meet Event!');
    console.log('Event ID:', meetEvent.id);
    console.log('\n=== EVENT DETAILS ===\n');

    // Fetch full event details
    const eventDetails = await calendar.events.get({
      calendarId: 'primary',
      eventId: meetEvent.id,
    });

    const event = eventDetails.data;

    // Log event date/time
    const startTime = event.start?.dateTime ?? event.start?.date;
    const endTime = event.end?.dateTime ?? event.end?.date;
    console.log('EVENT TITLE:', event.summary);
    console.log('START TIME:', startTime);
    console.log('END TIME:', endTime);
    console.log('');

    // Log Google Meet link
    if (event.hangoutLink) {
      console.log('GOOGLE MEET LINK:', event.hangoutLink);
    }
    console.log('');

    // Log attendees
    if (event.attendees && event.attendees.length > 0) {
      console.log('=== ATTENDEES ===\n');

      // Find the organizer/host
      const organizer = event.organizer;
      console.log('HOST:');
      console.log(`  Email: ${organizer.email}`);
      if (organizer.displayName) {
        console.log(`  Name: ${organizer.displayName}`);
      }
      console.log(`  Self: ${organizer.self ? 'Yes' : 'No'}`);
      console.log('');

      // Log other invitees
      console.log('OTHER INVITEES:');
      event.attendees.forEach((attendee, index) => {
        // Skip if this is the organizer
        if (attendee.email === organizer.email && attendee.organizer) {
          return;
        }

        console.log(`\n  Invitee ${index + 1}:`);
        console.log(`    Email: ${attendee.email}`);
        if (attendee.displayName) {
          console.log(`    Name: ${attendee.displayName}`);
        }
        console.log(`    Response Status: ${attendee.responseStatus}`);
        console.log(`    Optional: ${attendee.optional ? 'Yes' : 'No'}`);
        if (attendee.organizer) {
          console.log(`    Role: Organizer`);
        }
      });
    } else {
      console.log('No attendees found for this event.');
    }

    console.log('\n=== FULL EVENT DATA ===\n');
    console.log(JSON.stringify(event, null, 2));

    // Uncomment to stop the watch after testing
    // await stopCalendarWatch(calendar, watchData.id, watchData.resourceId);

  } catch (error) {
    console.error('Error fetching events:', error.message);
    console.error('Full error:', error);
  }
}
// listEvents();
export {
  authenticateWithPlaywright,
  setupCalendarWatch,
  stopCalendarWatch,
  listEvents,
  authenticateWithRefreshToken,
};

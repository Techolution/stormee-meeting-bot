import path from 'node:path';
import process from 'node:process';

// The scope for reading calendar events.
export const SCOPES = ['https://www.googleapis.com/auth/calendar.readonly'];
// The path to the credentials file.
export const CREDENTIALS_PATH = path.join(process.cwd(), '/services/integrations/credentials.json');

// Your webhook endpoint URL (must be HTTPS and publicly accessible)
export const WEBHOOK_URL = 'https://9bptz7pv-8080.inc1.devtunnels.ms/meeting_recorder_stormee/webhook';


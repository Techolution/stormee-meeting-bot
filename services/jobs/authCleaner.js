import cron from 'node-cron';
import fs from 'fs';

const AUTH_PATH = `${process.cwd()}/auth.json`;

cron.schedule('0 0 * * *', () => { // Runs every day at 12:00 AM (midnight)
  if (fs.existsSync(AUTH_PATH)) {
    fs.unlinkSync(AUTH_PATH);
    console.log('🧹 [AUTH CLEANER] auth.json deleted by cron');
  }
});

import { Queue, Worker, QueueEvents } from "bullmq";
import { redisConnection } from "../../loaders/redis.loaders.js";
import { authenticateWithPlaywright, setupCalendarWatch, stopCalendarWatch, } from "../integrations/calendarAPI.js";
import { google } from "googleapis";

// QUEUE SETUP
const calendarQueue = new Queue("calendar-channel", {
  connection: redisConnection,
});

// SCHEDULE JOB (Always create new channel first, delete old later)
async function scheduleChannelRenewal({
  oldChannelId,
  oldResourceId,
  expiration,
}) {
  const now = Date.now();
  const sixDaysMs = 6 * 24 * 60 * 60 * 1000; // 6 days
  let delay = Math.min(sixDaysMs, expiration - now);

  if (delay <= 0) {
    console.warn(
      `⚠ Old channel ${oldChannelId} is about to expire. Renew immediately.`
    );
    delay = 0;
  }

  const job = await calendarQueue.add(
    "renew-calendar-channel",
    { oldChannelId, oldResourceId },
    {
      delay,
      removeOnComplete: true,
      removeOnFail: false,
      jobId: oldChannelId, // Tracking by channel ID
    }
  );

  console.log(`🔁 Renewal scheduled: Job ${job.id}, delay ${delay}ms`);
  return job.id;
}

// CREATE INITIAL CHANNEL
async function createInitialCalendarChannel(calendarId = "primary") {
  console.log(`\n🚀 Creating initial Calendar Watch for: ${calendarId}`);

  const { oauth2Client } = await authenticateWithPlaywright();
  const calendar = google.calendar({ version: "v3", auth: oauth2Client });

  const watchData = await setupCalendarWatch(calendar, calendarId);
  console.log("🆕 Initial Channel Created:", watchData);

  // Schedule renewal (new channel will be created first, then old stopped)
  await scheduleChannelRenewal({
    oldChannelId: watchData.id,
    oldResourceId: watchData.resourceId,
    expiration: Number(watchData.expiration),
  });

  return watchData;
}

// WORKER – Auto renew channel
const calendarWorker = new Worker(
  "calendar-channel",
  async (job) => {
    const { oldChannelId, oldResourceId } = job.data;

    console.log(`\n🔄 Renewing Calendar Channel...`);
    console.log(`📌 Old Channel: ${oldChannelId}`);

    const { oauth2Client } = await authenticateWithPlaywright();
    const calendar = google.calendar({ version: "v3", auth: oauth2Client });

    // 1️⃣ Create new channel
    const newWatch = await setupCalendarWatch(calendar);
    console.log(`🆕 New Channel Created: ${newWatch.id}`);

    // save the newWatch logs to DB later

    // 2️⃣ Stop old channel
    await stopCalendarWatch(calendar, oldChannelId, oldResourceId);
    console.log(`🗑 Old Channel Stopped: ${oldChannelId}`);

    // 3️⃣ Schedule next renewal
    await scheduleChannelRenewal({
      oldChannelId: newWatch.id,
      oldResourceId: newWatch.resourceId,
      expiration: Number(newWatch.expiration),
    });

    return { success: true, renewedAt: new Date(), newChannelId: newWatch.id };
  },
  {
    connection: redisConnection,
    concurrency: 1, // Low concurrency for safety
  }
);

// EVENT LISTENERS
const queueEvents = new QueueEvents("calendar-channel", {
  connection: redisConnection,
});

queueEvents.on("completed", ({ jobId }) =>
  console.log(`🟢 Renewal job ${jobId} completed`)
);

queueEvents.on("failed", ({ jobId, failedReason }) =>
  console.error(`🔴 Renewal job ${jobId} failed → ${failedReason}`)
);

calendarWorker.on("error", (err) => {
  console.error("Worker Error (Calendar Channel):", err);
});

// GRACEFUL SHUTDOWN
async function shutdown() {
  console.log("\n🛑 Gracefully shutting down calendar scheduler...");
  await calendarWorker.close();
  await calendarQueue.close();
  await queueEvents.close();
  process.exit(0);
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);

export { scheduleChannelRenewal, createInitialCalendarChannel, calendarQueue, calendarWorker, queueEvents };

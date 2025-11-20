import { Queue, Worker, QueueEvents } from "bullmq";
import Redis from "ioredis";
import { MeetingManager } from "../meetingManager.js";

const manager = MeetingManager.getInstance();

// REDIS CONNECTION
const redisConnection = new Redis({
  host: "localhost",
  port: 6379,
  maxRetriesPerRequest: null, // Required for BullMQ
});

// QUEUE SETUP
const meetingQueue = new Queue("meeting-notifications", {
  connection: redisConnection,
});

// ADD / UPDATE MEETING JOB IN QUEUE
async function scheduleMeeting(meeting) {
  const now = Date.now();
  const startTimeMs = meeting.startTime.getTime();
  const endTimeMs = meeting.endTime.getTime(); // Ensure endTime exists

  // ❌ Invalid case – meeting already finished
  if (now >= endTimeMs) {
    throw new Error("Meeting end time has already passed. Cannot schedule.");
  }

  // 📌 If meeting has started but is still ongoing → trigger immediately
  let delay = startTimeMs - now;
  if (delay < 0) {
    delay = 0; // Immediate
  }

  // 🔍 Find existing job by meetingEventId
  const existingJob = await meetingQueue.getJob(meeting.meetingEventId);

  if (existingJob) {
    await existingJob.updateData(meeting);
    await existingJob.changeDelay(delay);

    // Promote to ensure it's back in queue (if already running)
    if (delay === 0) {
      await existingJob.promote();
    }

    console.log(
      `🔁 Updated existing meeting job ID: ${existingJob.id}, delay: ${delay}`
    );
    return existingJob.id;
  }

  // 🆕 Create new job
  const job = await meetingQueue.add("send-meeting-notification", meeting, {
    delay,
    removeOnComplete: true,
    removeOnFail: false,
    jobId: meeting.meetingEventId,
  });

  console.log(`🆕 Meeting scheduled with job ID: ${job.id}, delay: ${delay}`);
  return job.id;
}

// WORKER - PROCESSES JOBS
const worker = new Worker(
  "meeting-notifications",
  async (job) => {
    const meeting = job.data;

    console.log(`\n🔔 Meeting Starting Now!`);
    console.log(`📅 StartTime: ${meeting.startTime}`);
    console.log(`📅 EndTime: ${meeting.endTime}`);
    console.log(`🔗 URL: ${meeting.meetUrl}`);
    console.log(`👤 Organizer: ${meeting.organizer}`);
    console.log(`👥 Recipients: ${meeting.recipients.join(", ")}`);

    manager.createMeeting(
      meeting.meetUrl,
      {
        email: meeting.organizer,
      },
      false,
      meeting.recipients
    );

    console.log(`✅ Notifications sent for job ID: ${job.id}\n`);

    return { success: true, sentAt: new Date() };
  },
  {
    connection: redisConnection,
    concurrency: 5, // Process up to 5 jobs simultaneously
  }
);

// EVENT LISTENERS
const queueEvents = new QueueEvents("meeting-notifications", {
  connection: redisConnection,
});

queueEvents.on("completed", ({ jobId }) => {
  console.log(`✅ Job ${jobId} completed successfully`);
});

queueEvents.on("failed", ({ jobId, failedReason }) => {
  console.error(`❌ Job ${jobId} failed: ${failedReason}`);
});

worker.on("error", (err) => {
  console.error("Worker error:", err);
});

// GRACEFUL SHUTDOWN
async function shutdown() {
  console.log("\n🛑 Shutting down gracefully...");
  await worker.close();
  await meetingQueue.close();
  await queueEvents.close();
  await redisConnection.quit();
  process.exit(0);
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);

export { scheduleMeeting, meetingQueue, worker, queueEvents };

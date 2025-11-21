import Redis from "ioredis";

export const redisConnection = new Redis({
  host: "localhost",
  port: 6379,
  maxRetriesPerRequest: null, // Required for BullMQ
});

export const connectRedis = async () => {
  try {
    await redisConnection.ping();
    console.log('🚀 Redis connected successfully');
  } catch (error) {
    console.error('❌ Failed to connect to Redis:', error);
    process.exit(1);
  }
};

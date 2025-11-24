import Redis from "ioredis";
import dotenv from "dotenv";

dotenv.config();

export const redisConnection = new Redis({
  host: process.env.REDIS_HOST_IP,
  port: parseInt(process.env.REDIS_HOST_PORT),
  password: process.env.REDIS_HOST_PW,
  db: parseInt(process.env.REDIS_HOST_DB),
  maxRetriesPerRequest: null, // Required for BullMQ
  retryStrategy: (times) => {
    const delay = Math.min(times * 50, 2000);
    console.log(`Retry attempt ${times}, waiting ${delay}ms`);
    return delay;
  },
  connectTimeout: 10000, // 10 seconds
  enableReadyCheck: true,
  lazyConnect: true, // Don't connect immediately
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

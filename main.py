import os
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import socketio
import uvicorn
from routes.stormee_meet_bot_routes import router as meet_router

# Load environment variables
load_dotenv()

# Initialize FastAPI app
app = FastAPI(
    title="Meet API",
    description="API documentation for the Meet service",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow connections from any origin - adjust for production
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# API routes
app.include_router(meet_router, prefix="/api/meet")

# Root endpoint
@app.get("/")
async def root():
    return {"message": "API is running..."}

# OpenAPI JSON endpoint
@app.get("/openapi.json")
async def get_openapi():
    return JSONResponse(content=app.openapi())

# Initialize Socket.IO server with CORS configuration
sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins='*',  # Allow connections from any origin - adjust for production
    logger=True,
    engineio_logger=True
)

# Wrap FastAPI app with Socket.IO
socket_app = socketio.ASGIApp(
    sio,
    other_asgi_app=app
)

# WebSocket connection handler
@sio.event
async def connect(sid, environ):
    """Handle client connection"""
    print(f"🔌 A client connected via WebSocket: {sid}")

@sio.event
async def disconnect(sid):
    """Handle client disconnection"""
    print(f"🔌 Client disconnected: {sid}")

@sio.event
async def audioChunk(sid, data):
    """Handle incoming audio chunks from the bot"""
    meeting_id = data.get('meetingId')
    chunk_id = data.get('chunkId')
    timestamp = data.get('timestamp')
    audio_blob = data.get('audioBlob')
    audio_size = len(audio_blob) if audio_blob else "N/A"
    
    print(f"🎵 Received audio chunk from meeting {meeting_id}, chunk ID: {chunk_id}")
    print(f"📅 Timestamp: {timestamp}")
    print(f"📊 Audio data size: {audio_size} bytes")
    
    # TODO: Process the audio chunk (save to disk, forward to analysis service, etc.)
    # Example implementations:
    # - save_audio_chunk(meeting_id, chunk_id, timestamp, audio_blob)
    # - forward_to_transcription_service(data)
    # - store_in_database(data)

@sio.event
async def error(sid, data):
    """Handle connection errors"""
    print(f"❌ WebSocket error for client {sid}: {data}")


if __name__ == "__main__":
    PORT = int(os.getenv("PORT", 5000))
    
    print(f"🚀 Express server running on port {PORT}")
    print(f"🔌 WebSocket server running on port {PORT}")
    print(f"📋 API endpoints available at http://localhost:{PORT}/api/meet")
    
    # Start the combined HTTP and WebSocket server
    uvicorn.run(
        socket_app,
        host="0.0.0.0",
        port=PORT,
        log_level="info"
    )
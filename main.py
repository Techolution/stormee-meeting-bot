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

# Configure centralized logging
from services.websocket_events import register_websocket_handlers
from utilities.logging_config import configure_logging
from utilities.env_config import config

# Configure logging and validate all environment variables
# LOG_LEVEL is optional, so we safely get it
log_level = None
try:
    log_level = config.get('LOG_LEVEL')
except ValueError:
    pass  # LOG_LEVEL is optional

configure_logging(log_level=log_level)
config.validate()

# Initialize FastAPI app
app = FastAPI(
    title="Meet API",
    description="API documentation for the Meet service",
    version="1.0.0",
    docs_url="/api/meet/docs",
    redoc_url="/api/meet/redoc",
    openapi_url="/api/meet/openapi.json"
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
@app.get("/api/meet")
async def root():
    return {"message": "API is running..."}

# OpenAPI JSON endpoint
@app.get("/api/meet/openapi.json")
async def get_openapi():
    return JSONResponse(content=app.openapi())

# Initialize Socket.IO server with CORS configuration
sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins='*',  # Allow connections from any origin - adjust for production
    logger=False,
    engineio_logger=False
)

# Wrap FastAPI app with Socket.IO
socket_app = socketio.ASGIApp(
    sio,
    other_asgi_app=app,
    socketio_path="api/meet/socket.io"
)
register_websocket_handlers(sio=sio)


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
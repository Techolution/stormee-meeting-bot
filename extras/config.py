"""
Configuration for Meet Bot
Adjust these settings to improve stability
"""

import os

# Browser Configuration
BROWSER_CONFIG = {
    "headless": False,  # Set to True for production (requires Xvfb)
    "slow_mo": 100,  # Slow down operations by 100ms (helps with detection)
    "args": [
        # Anti-detection
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--disable-setuid-sandbox",
        "--no-sandbox",
        
        # Memory and stability
        "--disable-web-security",
        "--disable-features=IsolateOrigins,site-per-process",
        
        # Media
        "--use-fake-device-for-media-stream",
        "--use-fake-ui-for-media-stream",
        
        # Display
        "--start-maximized",
        "--window-size=1920,1080",
        
        # Performance
        "--disable-gpu",
    ]
}

# Timeouts (in milliseconds)
TIMEOUTS = {
    "page_load": 60000,  # 60 seconds
    "navigation": 30000,  # 30 seconds
    "element_wait": 10000,  # 10 seconds
}

# Retry Configuration
RETRY_CONFIG = {
    "max_retries": 8,
    "retry_delay": 5,  # seconds
}

# Google Meet Specific
MEET_CONFIG = {
    "guest_name": "Stormee.Ai",
    "default_mic_state": "off",
    "default_camera_state": "off",
}

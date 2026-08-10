"""
Debug script to test meet bot with verbose logging
"""

import asyncio
import logging
from services.stormee_meet_bot_service import meet_bot

# Get module-level logger
logger = logging.getLogger(__name__)

# Also enable Playwright debug logging
import os
os.environ['DEBUG'] = 'pw:api'

async def debug_join(meeting_url: str):
    """Debug mode join with detailed output"""
    logger.info("=" * 60)
    logger.info("DEBUG MODE - Meet Bot")
    logger.info("=" * 60)
    
    try:
        logger.info("Initializing bot...")
        logger.debug(f"Meeting URL: {meeting_url}")
        
        logger.info("Joining meeting...")
        await meet_bot.join_meeting(meeting_url, as_guest=True)
        
        logger.info("Bot joined successfully!")
        logger.info("Waiting 60 seconds before leaving...")
        logger.debug("Watch the browser window for any issues...")
        
        await asyncio.sleep(60)
        
        logger.info("Leaving meeting...")
        await meet_bot.leave_meeting()
        
        logger.info("Debug test completed successfully!")
        
    except Exception as e:
        logger.error(f"Error during debug test: {e}")
        logger.error(f"Exception type: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        
        # Try to cleanup
        try:
            await meet_bot.leave_meeting()
        except:
            pass

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        logger.info("Usage: python debug_bot.py <MEETING_URL>")
        sys.exit(1)
    
    meeting_url = sys.argv[1]
    asyncio.run(debug_join(meeting_url))

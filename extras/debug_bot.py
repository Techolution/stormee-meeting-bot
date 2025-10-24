"""
Debug script to test meet bot with verbose logging
"""

import asyncio
import logging
from services.meet_bot import meet_bot

# Enable detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Also enable Playwright debug logging
import os
os.environ['DEBUG'] = 'pw:api'

async def debug_join(meeting_url: str):
    """Debug mode join with detailed output"""
    print("=" * 60)
    print("🐛 DEBUG MODE - Meet Bot")
    print("=" * 60)
    
    try:
        print("\n1️⃣ Initializing bot...")
        print(f"Meeting URL: {meeting_url}")
        
        print("\n2️⃣ Joining meeting...")
        await meet_bot.join_meeting(meeting_url, as_guest=True)
        
        print("\n3️⃣ Bot joined successfully!")
        print("Waiting 60 seconds before leaving...")
        print("Watch the browser window for any issues...")
        
        await asyncio.sleep(60)
        
        print("\n4️⃣ Leaving meeting...")
        await meet_bot.leave_meeting()
        
        print("\n✅ Debug test completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Error during debug test: {e}")
        print(f"Exception type: {type(e).__name__}")
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
        print("Usage: python debug_bot.py <MEETING_URL>")
        sys.exit(1)
    
    meeting_url = sys.argv[1]
    asyncio.run(debug_join(meeting_url))

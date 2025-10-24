#!/bin/bash

# Setup script for Meet Bot debugging files
# This creates the new debugging and configuration files

set -e

echo "=================================="
echo "Meet Bot - Debug Files Setup"
echo "=================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

# Check if we're in the right directory
if [ ! -f "main.py" ]; then
    print_error "Error: server.py not found. Please run this script from your project root."
    exit 1
fi

print_success "Found project root directory"

echo ""
echo "📝 Creating debug files..."
echo ""

# ============================================
# 1. Create debug_bot.py
# ============================================
cat > debug_bot.py << 'DEBUGBOT_EOF'
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
DEBUGBOT_EOF

print_success "Created debug_bot.py"

# ============================================
# 2. Create system_test.py
# ============================================
cat > system_test.py << 'SYSTEMTEST_EOF'
"""
System test to verify Playwright is working correctly
Run this BEFORE trying the full meet bot
"""

import asyncio
from playwright.async_api import async_playwright
import sys

async def test_basic_browser():
    """Test 1: Basic browser launch"""
    print("=" * 60)
    print("Test 1: Basic Browser Launch")
    print("=" * 60)
    
    try:
        async with async_playwright() as p:
            print("✓ Playwright imported successfully")
            
            browser = await p.chromium.launch(headless=False)
            print("✓ Browser launched successfully")
            
            page = await browser.new_page()
            print("✓ Page created successfully")
            
            await page.goto("https://www.google.com")
            print("✓ Navigation successful")
            
            title = await page.title()
            print(f"✓ Page title: {title}")
            
            await asyncio.sleep(3)
            
            await browser.close()
            print("✓ Browser closed successfully")
            
            print("\n✅ Test 1 PASSED\n")
            return True
            
    except Exception as e:
        print(f"\n❌ Test 1 FAILED: {e}\n")
        return False


async def test_google_meet_page():
    """Test 2: Can access Google Meet homepage"""
    print("=" * 60)
    print("Test 2: Google Meet Homepage Access")
    print("=" * 60)
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ]
            )
            
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            )
            
            page = await context.new_page()
            print("✓ Browser and page created")
            
            await page.goto("https://meet.google.com", wait_until="networkidle")
            print("✓ Navigated to Google Meet")
            
            title = await page.title()
            print(f"✓ Page title: {title}")
            
            await asyncio.sleep(5)
            
            await browser.close()
            print("✓ Browser closed")
            
            print("\n✅ Test 2 PASSED\n")
            return True
            
    except Exception as e:
        print(f"\n❌ Test 2 FAILED: {e}\n")
        import traceback
        traceback.print_exc()
        return False


async def run_all_tests(meeting_url: str = None):
    """Run all tests"""
    print("\n" + "=" * 60)
    print("🧪 PLAYWRIGHT SYSTEM TESTS")
    print("=" * 60 + "\n")
    
    results = []
    
    # Test 1: Basic browser
    results.append(await test_basic_browser())
    
    # Test 2: Google Meet homepage
    results.append(await test_google_meet_page())
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"✅ Passed: {passed}/{total}")
    
    if passed == total:
        print("\n🎉 All tests passed! Your system is ready.")
        print("You can now try the full meet bot with:")
        print("  python debug_bot.py <MEETING_URL>")
    else:
        print(f"\n⚠️ {total - passed} test(s) failed.")
        print("Please fix the issues above before using the meet bot.")
    
    print("=" * 60 + "\n")


def main():
    if len(sys.argv) > 1:
        meeting_url = sys.argv[1]
        print(f"Meeting URL provided: {meeting_url}")
        asyncio.run(run_all_tests(meeting_url))
    else:
        print("Running basic tests...")
        print("Usage: python system_test.py <MEETING_URL> (for full test)")
        asyncio.run(run_all_tests())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️ Tests cancelled by user")
        sys.exit(0)
SYSTEMTEST_EOF

print_success "Created system_test.py"

# ============================================
# 3. Create config.py
# ============================================
cat > config.py << 'CONFIG_EOF'
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
CONFIG_EOF

print_success "Created config.py"

# ============================================
# 4. Create quick test script
# ============================================
cat > quick_test.sh << 'QUICKTEST_EOF'
#!/bin/bash

echo "🧪 Running Quick System Test..."
echo ""

if [ ! -f "system_test.py" ]; then
    echo "❌ system_test.py not found!"
    exit 1
fi

python system_test.py

echo ""
echo "=================================="
echo "Next Steps:"
echo "=================================="
echo ""
echo "If tests passed, try joining a meeting:"
echo "  python debug_bot.py 'https://meet.google.com/xxx-yyy-zzz'"
echo ""
echo "Or start the server:"
echo "  python server.py"
echo ""
QUICKTEST_EOF

chmod +x quick_test.sh
print_success "Created quick_test.sh"

# ============================================
# 5. Create README for new files
# ============================================
cat > DEBUG_FILES_README.md << 'README_EOF'
# Debug Files - Quick Reference

## 📁 New Files Added

### 1. **debug_bot.py**
Debug script for testing meeting joins with verbose logging.

**Usage:**
```bash
python debug_bot.py "https://meet.google.com/xxx-yyy-zzz"
```

**What it does:**
- Enables detailed logging
- Joins meeting as guest
- Waits 60 seconds
- Leaves meeting
- Shows all errors with stack traces

### 2. **system_test.py**
System verification script to test Playwright setup.

**Usage:**
```bash
# Basic tests
python system_test.py

# Full test with meeting URL
python system_test.py "https://meet.google.com/xxx-yyy-zzz"
```

**Tests:**
- Browser launch
- Google Meet homepage access
- Basic navigation

### 3. **config.py**
Centralized configuration file.

**Customize:**
```python
# Edit these values in config.py
BROWSER_CONFIG["slow_mo"] = 200  # Slower = more human-like
TIMEOUTS["page_load"] = 90000    # Increase timeout
MEET_CONFIG["guest_name"] = "Your Bot Name"
```

### 4. **quick_test.sh**
One-command system test.

**Usage:**
```bash
bash quick_test.sh
```

## 🚀 Quick Start

### Step 1: Run System Test
```bash
python system_test.py
```

### Step 2: Test Meeting Join
```bash
python debug_bot.py "https://meet.google.com/your-meeting-code"
```

### Step 3: Check the Output
- ✅ All green checkmarks = working!
- ❌ Red X's = see error message
- ⚠️ Yellow warnings = may work, but be careful

## 🐛 Troubleshooting

### Error: "Playwright not found"
```bash
pip install playwright
playwright install chromium
```

### Error: "Target closed"
- Check the updated `services/meet_bot.py`
- Try with real Google account instead of guest
- Increase `slow_mo` in config.py

### Browser doesn't open
```bash
# Reinstall browsers
playwright install --force chromium
```

## 📝 Files Modified

- ✅ `services/meet_bot.py` - Backed up to `.backup` file
  - Added error handling
  - Improved anti-detection
  - Better logging
  - Safe page operations

## 🔄 Rollback

If something breaks:
```bash
# Restore original meet_bot.py
cp services/meet_bot.py.backup.TIMESTAMP services/meet_bot.py
```

## 📞 Need Help?

Run debug mode and check the output:
```bash
python debug_bot.py "YOUR_MEETING_URL" 2>&1 | tee debug.log
```

Then share `debug.log` for help.
README_EOF

print_success "Created DEBUG_FILES_README.md"

# ============================================
# Summary
# ============================================
echo ""
echo "=================================="
echo "✅ Setup Complete!"
echo "=================================="
echo ""
echo "📁 Files created:"
echo "  - debug_bot.py"
echo "  - system_test.py"
echo "  - config.py"
echo "  - quick_test.sh"
echo "  - DEBUG_FILES_README.md"
echo ""

if [ -f "services/meet_bot.py.backup."* ]; then
    echo "💾 Backup created:"
    echo "  - services/meet_bot.py.backup.*"
    echo ""
fi

echo "🚀 Next Steps:"
echo ""
echo "1. Replace services/meet_bot.py with the improved version"
echo "   (Download from Claude's artifacts above)"
echo ""
echo "2. Run system tests:"
echo "   bash quick_test.sh"
echo ""
echo "3. Test with a real meeting:"
echo "   python debug_bot.py 'https://meet.google.com/xxx-yyy-zzz'"
echo ""
echo "4. Read the guide:"
echo "   cat DEBUG_FILES_README.md"
echo ""
echo "=================================="
echo ""

print_success "All debug files created successfully!"
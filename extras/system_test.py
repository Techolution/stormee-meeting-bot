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

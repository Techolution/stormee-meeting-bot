import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

PROFILE_DIR = Path("chrome_profile")


async def create_profile():
    print("🚀 Launching browser to setup persistent profile...")

    async with async_playwright() as p:
        # Launch persistent context using local system Chrome
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,  # Keep visible so you can log in manually
            channel="chromium",  # Uses real system Chrome to avoid bot-detection
            args=["--disable-blink-features=AutomationControlled"],
        )

        page = (
            context.pages[0] if context.pages else await context.new_page()
        )

        # Go to Google Login page
        print("🔗 Navigating to Google Login...")
        await page.goto(
            "https://accounts.google.com/ServiceLogin?service=wise&continue=https%3A%2F%2Fmeet.google.com%2F"
        )

        print(
            "\n👉 ACTION REQUIRED: Log in to your Google Account manually in the opened browser window."
        )
        print("👉 Complete any 2FA/Security prompts if required.")
        input(
            "\n✅ Press ENTER in this terminal ONLY AFTER you are fully logged in and see Google Meet... "
        )

        # Gracefully close context to flush all session data/cookies to disk
        await context.close()
        print("🎉 Profile saved successfully inside 'chrome_profile/' folder!")


if __name__ == "__main__":
    asyncio.run(create_profile())
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

FAKE_VIDEO = Path("extras/media/ai_vid.y4m").resolve()
FAKE_AUDIO = Path("extras/media/output.wav").resolve()


async def test_meet_with_fake_media(meeting_url: str):
    print("=" * 60)
    print("Google Meet Fake Audio/Video Test")
    print("=" * 60)

    if not FAKE_VIDEO.exists():
        raise FileNotFoundError(f"Missing video: {FAKE_VIDEO}")

    if not FAKE_AUDIO.exists():
        raise FileNotFoundError(f"Missing audio: {FAKE_AUDIO}")

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=False,
            channel="chromium",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
                "--use-fake-device-for-media-stream",
                "--use-fake-ui-for-media-stream",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",

                # Feed these files into Chromium's camera/microphone.
                f"--use-file-for-fake-video-capture={FAKE_VIDEO}",
                f"--use-file-for-fake-audio-capture={FAKE_AUDIO}",
            ],
        )

        context = await browser.new_context(
            viewport=None
        )

        # Explicitly grant Meet permissions.
        await context.grant_permissions(
            ["camera", "microphone"],
            origin="https://meet.google.com",
        )

        page = await context.new_page()

        print("✓ Browser started")
        print("✓ Fake microphone:", FAKE_AUDIO)
        print("✓ Fake camera:", FAKE_VIDEO)

        await page.goto(
            meeting_url,
            wait_until="domcontentloaded",
        )

        print("✓ Meet page opened")
        print("\nYou should now see the Meet preview.")
        print("Your fake WAV is the microphone input.")
        print("Your fake Y4M is the camera input.")
        print("\nPress Ctrl+C when finished.")

        # Keep browser alive so you can inspect Meet.
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            pass

        await browser.close()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) != 2:
        print("Usage:")
        print("  python meet_media_test.py <MEETING_URL>")
        sys.argv.append("https://meet.google.com/cij-yvaw-wpu")

    asyncio.run(test_meet_with_fake_media(sys.argv[1]))
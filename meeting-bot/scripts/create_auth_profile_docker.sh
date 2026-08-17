

rm -rf chrome_profile
mkdir -p chrome_profile

MAC_IP=$(ipconfig getifaddr en0 || ipconfig getifaddr en1)
xhost + "$MAC_IP"

source .env
docker run -i --rm \
  -e DISPLAY="$MAC_IP:0" \
  -e HEADLESS=false \
  -e GOOGLE_EMAIL \
  -e GOOGLE_PASSWORD \
  -v "$(pwd)/chrome_profile:/data/chrome_profile" \
  --ipc=host \
  meet-bot-python-image \
  python - <<'PY'
import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright

PROFILE = Path("/data/chrome_profile")


async def login_google():
    lock_file = PROFILE / "SingletonLock"
    if lock_file.exists():
        lock_file.unlink()

    email = os.environ["GOOGLE_EMAIL"]
    password = os.environ["GOOGLE_PASSWORD"]

    async with async_playwright() as p:
        print("🚀 Opening Chrome...")

        context = await p.chromium.launch_persistent_context(
            str(PROFILE),
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        page = context.pages[0] if context.pages else await context.new_page()

        await page.goto(
            "https://accounts.google.com/",
            wait_until="domcontentloaded"
        )

        # --------------------------------------------------
        # EMAIL
        # --------------------------------------------------
        email_input = page.get_by_label("Email or phone")

        await email_input.wait_for(
            state="visible",
            timeout=30000
        )

        print("📧 Entering email...")
        await email_input.press_sequentially(email, delay=80)
        await asyncio.sleep(4)
        next_button = page.get_by_role("button", name="Next")
        await next_button.click()

        # --------------------------------------------------
        # PASSWORD
        # --------------------------------------------------
        password_input = page.get_by_label("Enter your password")

        await password_input.wait_for(
            state="visible",
            timeout=30000
        )

        print("🔑 Entering password...")
        await password_input.press_sequentially(password, delay=80)
        await asyncio.sleep(20)

        # --------------------------------------------------
        # WAIT FOR GOOGLE'S SECURITY STEPS
        # --------------------------------------------------
        print()
        print("=" * 65)
        print("Google login credentials submitted.")
        print()
        print("If Google asks for:")
        print("  • 2-Step Verification")
        print("  • CAPTCHA")
        print("  • Passkey")
        print("  • suspicious-login confirmation")
        print("complete it manually in the Chrome window.")
        print()
        print("After login is completely finished, return here")
        print("and press ENTER.")
        print("=" * 65)
        print()

        # await asyncio.to_thread(
        #     input,
        #     "Press [ENTER] after Google login is complete..."
        # )

        await context.close()

        print()
        print("✅ Chrome profile saved!")
        print(f"📁 {PROFILE}")


asyncio.run(login_google())

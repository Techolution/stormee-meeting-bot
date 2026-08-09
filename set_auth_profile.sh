# docker run -it --rm \
#   -v "$(pwd)/chrome_profile:/app/chrome_profile" \
#   --ipc=host \
#   meet-bot-python-image \
#   xvfb-run --server-args="-screen 0 1280x1024x24" python -c "
# import asyncio
# from pathlib import Path
# from playwright.async_api import async_playwright

# async def main():
#     profile_dir = Path('/app/chrome_profile')
#     lock_file = profile_dir / 'SingletonLock'
#     if lock_file.exists():
#         lock_file.unlink()

#     async with async_playwright() as p:
#         print('🚀 Launching Chromium under Xvfb...')
#         context = await p.chromium.launch_persistent_context(
#             str(profile_dir),
#             headless=False,
#             args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
#         )
#         page = context.pages[0] if context.pages else await context.new_page()
#         await page.goto('https://accounts.google.com')
#         print('✅ Session initialized under Xvfb! Saving profile...')
#         await asyncio.sleep(3)
#         await context.close()

# asyncio.run(main())
# "

rm -rf chrome_profile
mkdir chrome_profile
# Get Mac IP and grant X11 access
MAC_IP=$(ipconfig getifaddr en0 || ipconfig getifaddr en1)
xhost + $MAC_IP

# Launch interactive Chrome window bound to your new chrome_profile directory
docker run -it --rm \
  -e DISPLAY=$MAC_IP:0 \
  -e HEADLESS=false \
  -v "$(pwd)/chrome_profile:/app/chrome_profile" \
  --ipc=host \
  meet-bot-python-image \
  python -c "
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

async def create_new_profile():
    profile_dir = Path('/app/chrome_profile')
    lock_file = profile_dir / 'SingletonLock'
    if lock_file.exists():
        lock_file.unlink()

    async with async_playwright() as p:
        print('🚀 Opening Chrome for new Google profile login...')
        context = await p.chromium.launch_persistent_context(
            str(profile_dir),
            headless=False,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled'
            ]
        )
        page = context.pages[0] if context.pages else await context.new_page()
        
        # Navigate to Google Login
        await page.goto('https://accounts.google.com')
        
        print('\n' + '='*60)
        print('👉 Log into your Google Account in the Chrome window.')
        print('👉 Once logged in, press ENTER in this terminal to save session.')
        print('='*60 + '\n')
        
        input('Press [ENTER] here AFTER completing Google Login...')
        await context.close()
        print('✅ Profile successfully saved to /app/chrome_profile!')

asyncio.run(create_new_profile())
"
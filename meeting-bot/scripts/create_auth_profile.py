#!/usr/bin/env python3
"""Create a persistent Chromium profile signed in to Google.

Without a profile the bot joins meetings as a guest and needs a host to admit it.
With one, it joins as the signed-in account and is usually admitted immediately.

Run interactively, once:

    make auth-profile

A browser window opens. Sign in to the Google account the bot should use, then
return here and press Enter.

The resulting directory holds live Google session cookies. Treat it as a
credential: it is in .gitignore, and in a cluster it should be mounted as a
secret rather than baked into an image.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

try:
    from playwright.async_api import async_playwright
except ImportError:  # pragma: no cover - operator-facing script
    sys.exit("playwright is not installed. Run: make install")

SIGN_IN_URL = "https://accounts.google.com"

#: Chromium refuses to start against a profile another process is using. A pod
#: killed mid-run leaves this behind, and clearing it is safe once we know no
#: browser is attached.
LOCK_FILES = ("SingletonLock", "SingletonCookie", "SingletonSocket")

LAUNCH_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
]


def clear_stale_locks(profile_dir: Path) -> None:
    for name in LOCK_FILES:
        lock = profile_dir / name
        if lock.exists() or lock.is_symlink():
            lock.unlink(missing_ok=True)
            print(f"  removed stale lock: {name}")


async def create_profile(profile_dir: Path, *, headless: bool) -> int:
    profile_dir.mkdir(parents=True, exist_ok=True)
    clear_stale_locks(profile_dir)

    print(f"\nProfile directory: {profile_dir.resolve()}")
    print("Launching Chromium...\n")

    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir.resolve()),
            headless=headless,
            channel="chromium",
            args=LAUNCH_ARGS,
            viewport=None,
        )
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(SIGN_IN_URL, wait_until="domcontentloaded")

            print("=" * 68)
            print("  Sign in to the Google account the bot should use.")
            print("  Complete any two-factor prompts.")
            print("  Then return here and press Enter.")
            print("=" * 68)

            # input() blocks; run it off the loop so the browser stays responsive.
            await asyncio.to_thread(input, "\nPress Enter once signed in... ")

            signed_in = await _looks_signed_in(page)
        finally:
            await context.close()

    if not signed_in:
        print(
            "\nCould not confirm a signed-in session. The profile was saved, but the "
            "bot may still fall back to guest joins.\n"
            "Re-run this script if joins are not being admitted automatically."
        )
        return 1

    print(f"\nProfile saved to {profile_dir.resolve()}")
    print("Point the bot at it with:\n")
    print(f"    BROWSER_PROFILE_DIR={profile_dir}\n")
    print("Do not commit this directory: it contains live session cookies.")
    return 0


async def _looks_signed_in(page) -> bool:  # type: ignore[no-untyped-def]
    """Best-effort check that a Google session exists.

    Cookie names are not a stable contract, so a negative result is reported as
    unconfirmed rather than treated as failure.
    """
    try:
        cookies = await page.context.cookies("https://accounts.google.com")
    except Exception:  # noqa: BLE001 - diagnostics only
        return False
    return any(cookie.get("name") in {"SID", "__Secure-1PSID"} for cookie in cookies)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=Path("chrome_profile"),
        help="Where to write the profile (default: chrome_profile)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run without a window. Only useful if you can drive it another way.",
    )
    args = parser.parse_args()

    if args.headless:
        print("Warning: signing in headlessly is rarely possible; expect to need a window.")

    try:
        return asyncio.run(create_profile(args.profile_dir, headless=args.headless))
    except KeyboardInterrupt:
        print("\nCancelled. Nothing was saved.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

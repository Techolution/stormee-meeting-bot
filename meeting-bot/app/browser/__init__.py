"""Browser automation.

This package knows about Chromium and Playwright. It does not know about
meetings: no Google Meet selector, join flow, or caption format appears here.
That separation is what lets a second meeting platform be added without
touching browser code.
"""

from app.browser.browser import Browser
from app.browser.browser_manager import BrowserManager
from app.browser.models import BrowserOptions, BrowserStatus, SessionMode

__all__ = ["Browser", "BrowserManager", "BrowserOptions", "BrowserStatus", "SessionMode"]

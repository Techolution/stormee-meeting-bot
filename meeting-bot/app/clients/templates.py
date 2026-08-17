"""Email templates.

Kept separate from :mod:`app.clients.mail` so that changing how a message looks
never touches how it is delivered. Values are escaped before interpolation —
meeting titles and project names are user-supplied and reach an HTML document.
"""

from __future__ import annotations

from datetime import date
from html import escape

#: Matches the legacy footer. The year is derived rather than hardcoded so it
#: does not silently go stale in January.
_BRAND_FOOTER = f"This is an automated notification. © {date.today().year} Techolution"

_MEETING_FILE_UPLOADED_HTML = """\
<!DOCTYPE html>
<html>
  <body style="background:#fff;font-family:Arial,Helvetica,sans-serif;max-width:680px;margin:0 auto;padding:20px 0;">
    <div style="text-align:center;padding:32px 40px 0;border:1px solid #e8e8e8;border-radius:8px;margin:0 20px;">

      <div style="color:#2563eb;font-size:13px;font-weight:500;margin-bottom:8px;letter-spacing:0.3px;">
        Meeting {file_type_title}
      </div>

      <div style="font-size:22px;font-weight:700;color:#111;margin-bottom:10px;">
        Meeting {file_type_title} Uploaded
      </div>

      <div style="text-align:center;font-size:20px;color:#333;margin-bottom:24px;">
        <strong>{meeting_title}</strong>
      </div>

      <div style="text-align:left;margin-bottom:28px;">
        <div style="font-size:14px;color:#333;margin-bottom:16px;">
          Hello <span style="color:#1a73e8;font-weight:600;">{user_name}</span>,
        </div>

        <div style="background:#f0f7ff;border-left:4px solid #2563eb;border-radius:4px;padding:16px 18px;">
          <div style="font-size:14px;color:#333;margin-bottom:10px;">
            <span style="display:inline-block;width:28px;height:28px;line-height:28px;text-align:center;
                         border-radius:50%;background:#dbeafe;color:#1d4ed8;font-weight:600;
                         margin-right:8px;vertical-align:middle;">{user_initial}</span>
            <span style="vertical-align:middle;">
              Your meeting {file_type} <strong>{meeting_title}</strong> has been successfully
              uploaded to the project <strong>{project_name}</strong>.
            </span>
          </div>
          <div style="font-size:14px;color:#555;margin-top:8px;line-height:1.5;">
            You can open the project to review the {file_type} and continue working with the
            meeting content.
          </div>
        </div>
      </div>

      <div style="text-align:center;margin-bottom:28px;">
        <a href="{project_url}" style="display:inline-block;background:#2563eb;color:#fff;border-radius:6px;
                                       padding:13px 48px;font-size:15px;font-weight:600;text-decoration:none;">
          Open Project
        </a>
      </div>

      <div style="font-size:12px;color:#777;margin-bottom:28px;line-height:1.6;">
        The meeting {file_type} is now available in your project. You can open the project using
        the button above.
      </div>

      <div style="border-top:1px solid #e8e8e8;padding:16px 0;font-size:11px;color:#aaa;">
        {footer}
      </div>

    </div>
  </body>
</html>
"""


def render_meeting_file_uploaded(
    *,
    user_name: str,
    project_name: str,
    project_url: str,
    meeting_title: str,
    file_type: str = "recording",
) -> tuple[str, str]:
    """Build the "your meeting file is ready" message.

    Returns:
        ``(subject, html_body)``.
    """
    safe_file_type = escape(file_type or "recording")
    safe_title = escape(meeting_title or "Untitled meeting")
    display_name = user_name or "there"

    subject = f"Meeting {safe_file_type.capitalize()} Uploaded: {meeting_title or 'Untitled meeting'}"

    html = _MEETING_FILE_UPLOADED_HTML.format(
        file_type=safe_file_type,
        file_type_title=safe_file_type.capitalize(),
        meeting_title=safe_title,
        user_name=escape(display_name),
        user_initial=escape(display_name[:1].upper() or "U"),
        project_name=escape(project_name or "your project"),
        project_url=escape(project_url, quote=True),
        footer=_BRAND_FOOTER,
    )
    return subject, html

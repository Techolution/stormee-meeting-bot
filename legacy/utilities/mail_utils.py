import logging
from typing import Optional
import httpx
from utilities.env_config import config

# Get module-level logger
logger = logging.getLogger(__name__)


class EmailGenerator:
    def __init__(self):
        self.brand_purple = "#5634E1"
        self.btn_green = "#22C55E"
        self.btn_red = "#EF4444"
        # BACKEND_URL is required to be set via environment variable
        try:
            self.backend_url = config.get('BACKEND_URL')
        except ValueError:
            logger.error("BACKEND_URL environment variable not set")
            raise

    def generate_meeting_file_uploaded_email(
        self,
        user_name: str,
        user_email: str,
        project_name: str,
        project_url: str,
        meeting_title: str,
        file_type: Optional[str] = "transcript"
    ):
        """
        Generates an email notification when a meeting file
        has been uploaded to a project.

        Returns:
            tuple: (subject, html_body)
        """
        file_type_capitalized = file_type.capitalize()
        subject = f"Meeting {file_type_capitalized} Uploaded: {meeting_title}"
        user_initial = (user_name[:1] or "U").upper()

        html = f"""
        <!DOCTYPE html>
        <html>
        <body style="
            background: #fff;
            font-family: Arial, sans-serif;
            max-width: 680px;
            margin: 0 auto;
            padding: 20px 0;
        ">
            <div style="
                text-align: center;
                padding: 32px 40px 0;
                border: 1px solid #e8e8e8;
                border-radius: 8px;
                margin: 0 20px;
            ">

                <div style="
                    color: #2563eb;
                    font-size: 13px;
                    font-weight: 500;
                    margin-bottom: 8px;
                    letter-spacing: 0.3px;
                ">
                    Meeting {file_type_capitalized}
                </div>

                <div style="
                    font-size: 22px;
                    font-weight: 700;
                    color: #111;
                    margin-bottom: 10px;
                ">
                    Meeting {file_type_capitalized} Uploaded
                </div>

                <div style="
                    text-align: center;
                    font-size: 20px;
                    color: #333;
                    margin-bottom: 24px;
                ">
                    <strong>{meeting_title}</strong>
                </div>

                <div style="
                    text-align: left;
                    margin-bottom: 28px;
                ">

                    <div style="
                        font-size: 14px;
                        color: #333;
                        margin-bottom: 16px;
                    ">
                        Hello
                        <span style="
                            color: #1a73e8;
                            font-weight: 600;
                        ">
                            {user_name}
                        </span>,
                    </div>

                    <div style="
                        background: #f0f7ff;
                        border-left: 4px solid #2563eb;
                        border-radius: 4px;
                        padding: 16px 18px;
                    ">

                        <div style="
                            font-size: 14px;
                            color: #333;
                            margin-bottom: 10px;
                        ">
                            <span style="
                                display: inline-block;
                                width: 28px;
                                height: 28px;
                                line-height: 28px;
                                text-align: center;
                                border-radius: 50%;
                                background: #dbeafe;
                                color: #1d4ed8;
                                font-weight: 600;
                                margin-right: 8px;
                                vertical-align: middle;
                            ">
                                {user_initial}
                            </span>

                            <span style="vertical-align: middle;">
                                Your meeting {file_type}
                                <strong>{meeting_title}</strong>
                                has been successfully uploaded to the project
                                <strong>{project_name}</strong>.
                            </span>
                        </div>

                        <div style="
                            font-size: 14px;
                            color: #555;
                            margin-top: 8px;
                            line-height: 1.5;
                        ">
                            You can open the project to review the {file_type}
                            and continue working with the meeting content.
                        </div>

                    </div>
                </div>

                <div style="
                    text-align: center;
                    margin-bottom: 28px;
                ">
                    <a href="{project_url}" style="
                        display: inline-block;
                        background: #2563eb;
                        color: #fff;
                        border-radius: 6px;
                        padding: 13px 48px;
                        font-size: 15px;
                        font-weight: 600;
                        text-decoration: none;
                    ">
                        Open Project
                    </a>
                </div>

                <div style="
                    font-size: 12px;
                    color: #777;
                    margin-bottom: 28px;
                    line-height: 1.6;
                ">
                    The meeting {file_type} is now available in your project.
                    You can open the project using the button above.
                </div>

                <div style="
                    border-top: 1px solid #e8e8e8;
                    padding: 16px 0;
                    font-size: 11px;
                    color: #aaa;
                ">
                    This is an automated notification. © 2026 Techolution
                </div>

            </div>
        </body>
        </html>
        """

        return subject, html


class EmailSender:
    def __init__(self):
        self.backend_url = "https://dev.appmod.ai"

    async def send_email(
        self,
        to_email: str,
        subject: str,
        body: str,
        cc: str = "",
    ):
        """
        Sends an email through the backend email service.
        """

        payload = {
            "to_email": to_email,
            "subject": subject,
            "body": body,
            "cc": cc,
        }

        endpoint = f"{self.backend_url}/backend/utility/cw-email"

        logger.info(
            f"Sending email to={to_email}, cc={cc}, subject={subject}"
        )
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    endpoint,
                    json=payload,
                )

            if response.status_code == 200:
                logger.info(
                    f"Meeting file email sent successfully to={to_email}"
                )
            else:
                logging.error(
                    f"Meeting file email failed "
                    f"to={to_email} with status={response.status_code}, "
                    f"response={response.text}"
                )

            return response
        except Exception as e:
            logging.error(
                f"Meeting file email failed "
                f"to={to_email}: {str(e)}"
            )
 
    async def send_meeting_file_uploaded_email(
        self,
        user_name: str,
        user_email: str,
        project_name: str,
        project_url: str,
        meeting_title: str,
        file_type: str
    ):
        """
        Sends meeting file uploaded notification to the user.
        """

        logger.info(
            f"Preparing meeting {file_type} notification "
            f"for user={user_email}, meeting_title={meeting_title}"
        )

        generator = EmailGenerator()

        subject, html_body = (
            generator.generate_meeting_file_uploaded_email(
                user_name=user_name,
                user_email=user_email,
                project_name=project_name,
                project_url=project_url,
                meeting_title=meeting_title,
                file_type=file_type
            )
        )

        return await self.send_email(
            to_email=user_email,
            subject=subject,
            body=html_body,
        )

email_sender = EmailSender()

# if __name__ == "__main__":
#     import asyncio

#     async def test_email():
#         sender = EmailSender()
#         await sender.send_meeting_file_uploaded_email(
#             user_name="John Doe",
#             user_email="swikrit.shukla@techolution.com",
#             project_name="Project Alpha",
#             project_url="https://dev.appmod.ai/projects/12345",
#             meeting_title="Meeting Test 2026-06-15",
#         )
#     asyncio.run(test_email())
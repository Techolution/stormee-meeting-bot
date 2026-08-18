"""
Client used by the Bot Handler to communicate with Meeting API.
"""


class MeetingApiClient:
    async def report_event(self, session_id: str, event: str, payload=None):
        raise NotImplementedError

    async def report_error(self, session_id: str, error: str):
        raise NotImplementedError

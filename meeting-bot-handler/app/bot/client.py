"""
HTTP client for communicating with an individual meeting-bot instance.

The handler talks to the Bot through this client.
It must not contain Kubernetes logic.
"""


class BotClient:
    async def health(self, base_url: str):
        raise NotImplementedError

    async def get_status(self, base_url: str):
        raise NotImplementedError

    async def start_recording(self, base_url: str):
        raise NotImplementedError

    async def stop_recording(self, base_url: str):
        raise NotImplementedError

    async def start_transcription(self, base_url: str):
        raise NotImplementedError

    async def stop_transcription(self, base_url: str):
        raise NotImplementedError

    async def leave(self, base_url: str):
        raise NotImplementedError

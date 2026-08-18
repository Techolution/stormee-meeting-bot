"""
Redis access for ephemeral Bot runtime/heartbeat information.

Redis must not become the durable source of truth for Bot sessions.
"""


class RedisRepository:
    async def get_heartbeat(self, session_id: str):
        raise NotImplementedError

    async def set_heartbeat(self, session_id: str, value):
        raise NotImplementedError

    async def delete_heartbeat(self, session_id: str):
        raise NotImplementedError

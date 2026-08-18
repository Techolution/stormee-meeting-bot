from pydantic import BaseModel


class BotStatusResponse(BaseModel):
    session_id: str
    status: str
    healthy: bool | None = None

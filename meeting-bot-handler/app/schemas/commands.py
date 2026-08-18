from pydantic import BaseModel


class CommandResponse(BaseModel):
    session_id: str
    command: str
    status: str

from pydantic import BaseModel


class CreateBotSessionRequest(BaseModel):
    session_id: str
    meeting_id: str
    meeting_url: str


class CreateBotSessionResponse(BaseModel):
    session_id: str
    status: str

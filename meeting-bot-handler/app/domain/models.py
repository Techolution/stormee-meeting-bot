from dataclasses import dataclass
from datetime import datetime

from app.domain.enums import BotSessionStatus


@dataclass
class BotSession:
    session_id: str
    meeting_id: str
    status: BotSessionStatus

    k8s_job_name: str | None = None
    k8s_service_name: str | None = None
    k8s_namespace: str | None = None

    created_at: datetime | None = None
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    failed_at: datetime | None = None
    updated_at: datetime | None = None

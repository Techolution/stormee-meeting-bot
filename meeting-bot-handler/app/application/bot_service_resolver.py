from dataclasses import dataclass
from typing import Any, Optional
from app.domain.exceptions import BotServiceNotAssignedError


@dataclass(frozen=True)
class BotTarget:
    service_url: str
    worker_id: Optional[str] = None


class BotServiceResolver:
    """Resolves the target execution destination for a bot session."""

    def resolve(self, session: Any) -> BotTarget:
        service_url = getattr(session, "bot_service_url", None)
        if not service_url:
            raise BotServiceNotAssignedError(
                f"Session {getattr(session, 'session_id', 'unknown')} has no assigned bot_service_url"
            )
        return BotTarget(
            service_url=service_url,
            worker_id=getattr(session, "bot_worker_id", None)
        )
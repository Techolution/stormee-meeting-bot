"""HTTP models for health and status endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from app.schemas.common import CamelCaseModel


class HealthResponse(CamelCaseModel):
    """Liveness. Answers "is this process up?" and nothing more."""

    status: str = Field(default="ok")
    service: str
    version: str
    environment: str


class DependencyStatus(CamelCaseModel):
    """One dependency's reachability."""

    name: str
    healthy: bool
    detail: str | None = None


class ReadinessResponse(CamelCaseModel):
    """Readiness. Answers "can this process take work?"."""

    ready: bool
    dependencies: list[DependencyStatus] = Field(default_factory=list)


class ComponentStatus(CamelCaseModel):
    """Runtime status of one subsystem within a session."""

    name: str
    status: str
    detail: dict[str, Any] | None = None


class SessionStatusResponse(CamelCaseModel):
    """What a single meeting session is doing right now."""

    meeting_id: str = Field(..., alias="meetingId")
    session_id: str = Field(..., alias="sessionId")
    status: str
    started_at: str | None = Field(default=None, alias="startedAt")
    uptime_seconds: float = Field(default=0.0, alias="uptimeSeconds")
    participant_count: int = Field(default=0, alias="participantCount")
    components: list[ComponentStatus] = Field(default_factory=list)
    last_heartbeat: str | None = Field(default=None, alias="lastHeartbeat")


class ServiceStatusResponse(CamelCaseModel):
    """Everything this pod is currently doing."""

    service: str
    version: str
    environment: str
    uptime_seconds: float = Field(..., alias="uptimeSeconds")
    active_sessions: int = Field(..., alias="activeSessions")
    sessions: list[SessionStatusResponse] = Field(default_factory=list)
    configuration: dict[str, Any] = Field(default_factory=dict)

"""Status and cluster-visibility response models."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class SessionStatusResponse(BaseModel):
    """Durable state first, live pod state as enrichment."""

    session_id: str
    meeting_id: str
    meeting_status: str
    bot_status: str
    recording_status: str
    transcription_status: str
    last_error: Optional[str] = None
    timestamps: Dict[str, Optional[str]]
    #: What the pod reports right now. Null when it could not be reached.
    runtime: Optional[Dict[str, Any]] = None
    runtime_error: Optional[str] = None


class BotPodView(BaseModel):
    """One bot pod as the handler sees it."""

    name: str
    ip: str
    base_url: str
    ready: Optional[bool] = None
    node_name: Optional[str] = None


class BotPodListResponse(BaseModel):
    """Cluster view: what the handler can actually reach."""

    namespace: str
    label_selector: str
    discovery_available: bool
    detail: Optional[str] = None
    total: int
    free: int
    pods: List[BotPodView]


class DependencyStatus(BaseModel):
    name: str
    healthy: bool
    detail: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    service: str
    environment: str


class ReadinessResponse(BaseModel):
    ready: bool
    dependencies: List[DependencyStatus]

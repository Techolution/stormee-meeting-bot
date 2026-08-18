from __future__ import annotations

from enum import Enum


class MeetingStatus(str, Enum):
    CREATED = "CREATED"
    STARTING = "STARTING"
    ACTIVE = "ACTIVE"
    LEAVING = "LEAVING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class BotStatus(str, Enum):
    PENDING = "PENDING"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


class RecordingStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    STARTING = "STARTING"
    RECORDING = "RECORDING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


class TranscriptionStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# Backward-compatibility alias
BotSessionStatus = BotStatus
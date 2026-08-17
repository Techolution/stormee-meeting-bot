"""In-meeting chat: collection and commands.

Two jobs that share one poll loop. Chat messages are meeting content worth
keeping, and some of them are instructions — a participant typing
``stormee start recording`` expects the bot to act.

Commands are registered rather than hard-coded, so adding one is a
registration at wiring time instead of another branch in a polling loop. That
also keeps this module free of any knowledge about recording or transcription;
it recognises a phrase and calls a callback.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from app.core.tasks import TaskSupervisor
from app.meeting_platform.base import MeetingPlatform
from app.meeting_platform.models import ChatMessage

logger = logging.getLogger(__name__)

#: Invoked when a command phrase is recognised, with the message that triggered it.
CommandHandler = Callable[[ChatMessage], Awaitable[None]]

#: Invoked for every new chat message.
MessageHandler = Callable[[ChatMessage], Awaitable[None]]

_POLL_TASK = "chat_poll"
_MAX_CONSECUTIVE_ERRORS = 30


class ChatMonitor:
    """Polls the chat panel, collects messages, and dispatches commands."""

    def __init__(
        self,
        *,
        platform: MeetingPlatform,
        meeting_id: str,
        command_prefix: str = "stormee",
        commands_enabled: bool = True,
        poll_interval_seconds: float = 1.0,
    ) -> None:
        self._platform = platform
        self._meeting_id = meeting_id
        self._command_prefix = command_prefix.lower().strip()
        self._commands_enabled = commands_enabled
        self._poll_interval = poll_interval_seconds

        self._tasks = TaskSupervisor(f"chat:{meeting_id}")
        self._messages: list[ChatMessage] = []
        self._seen_ids: set[str] = set()
        self._commands: dict[str, CommandHandler] = {}
        self._on_message: MessageHandler | None = None
        self._active = False

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def messages(self) -> list[ChatMessage]:
        """Every message collected so far, in arrival order."""
        return list(self._messages)

    @property
    def message_count(self) -> int:
        return len(self._messages)

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_command(self, phrase: str, handler: CommandHandler) -> None:
        """Bind a phrase to a handler.

        ``phrase`` is matched after the command prefix, case-insensitively.
        Registering ``"start recording"`` responds to ``stormee start recording``.
        """
        self._commands[phrase.lower().strip()] = handler
        logger.debug(
            "Chat command registered",
            extra={"meeting_id": self._meeting_id, "phrase": phrase},
        )

    def on_message(self, handler: MessageHandler) -> None:
        """Register a callback for every new message."""
        self._on_message = handler

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Open the chat panel and begin polling."""
        if self._active:
            return

        if not self._platform.capabilities.supports_chat:
            logger.info(
                "Chat monitoring unavailable on this platform",
                extra={"meeting_id": self._meeting_id},
            )
            return

        self._active = True
        await self._platform.open_chat_panel()
        self._tasks.spawn(_POLL_TASK, self._poll_loop())
        logger.info("Chat monitoring started", extra={"meeting_id": self._meeting_id})

    async def stop(self) -> list[ChatMessage]:
        """Stop polling and return everything collected."""
        if not self._active:
            return self.messages

        self._active = False
        await self._tasks.cancel_all()
        logger.info(
            "Chat monitoring stopped",
            extra={"meeting_id": self._meeting_id, "message_count": len(self._messages)},
        )
        return self.messages

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        """Read the chat panel on an interval until cancelled.

        Called by: nothing. Spawned as a background task by :meth:`start` — see
        docs/ENTRY_POINTS.md §5.
        """
        consecutive_errors = 0

        while True:
            try:
                current = await self._platform.get_chat_messages()
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - transient reads are normal
                consecutive_errors += 1
                logger.debug(
                    "Chat poll failed",
                    extra={"meeting_id": self._meeting_id, "reason": str(error)},
                )
                if consecutive_errors >= _MAX_CONSECUTIVE_ERRORS:
                    logger.error(
                        "Abandoning chat monitoring after repeated failures",
                        extra={"meeting_id": self._meeting_id},
                    )
                    return
                await asyncio.sleep(self._poll_interval * 2)
                continue

            consecutive_errors = 0

            for message in current:
                if message.message_id in self._seen_ids:
                    continue
                self._seen_ids.add(message.message_id)
                await self._handle_new_message(message)

            await asyncio.sleep(self._poll_interval)

    async def _handle_new_message(self, message: ChatMessage) -> None:
        """Record a message and act on it if it is a command."""
        self._messages.append(message)
        logger.debug(
            "Chat message received",
            extra={"meeting_id": self._meeting_id, "sender": message.sender},
        )

        if self._on_message is not None:
            try:
                await self._on_message(message)
            except Exception as error:
                logger.error("Chat message handler failed", exc_info=error)

        if self._commands_enabled:
            await self._dispatch_command(message)

    async def _dispatch_command(self, message: ChatMessage) -> None:
        """Run the handler for a recognised command phrase.

        Called by: the chat poll loop, when a participant types a command in the
        meeting. Handlers registered in
        ``MeetingSession._register_chat_commands`` — see docs/ENTRY_POINTS.md §4.

        Longest match wins, so ``"start caption recording"`` is not shadowed by
        ``"start recording"``.
        """
        text = message.text.lower().strip()
        if self._command_prefix and not text.startswith(self._command_prefix):
            return

        remainder = text[len(self._command_prefix) :].strip()
        match = next(
            (phrase for phrase in sorted(self._commands, key=len, reverse=True) if remainder.startswith(phrase)),
            None,
        )
        if match is None:
            logger.debug(
                "Unrecognised chat command",
                extra={"meeting_id": self._meeting_id, "command": remainder[:60]},
            )
            return

        logger.info(
            "Executing chat command",
            extra={"meeting_id": self._meeting_id, "command": match, "sender": message.sender},
        )
        try:
            await self._commands[match](message)
        except Exception as error:
            logger.error(
                "Chat command failed",
                exc_info=error,
                extra={"meeting_id": self._meeting_id, "command": match},
            )

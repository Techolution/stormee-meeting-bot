"""Graceful shutdown manager for MeetBot service.

Handles SIGTERM/SIGINT signals and coordinates graceful shutdown of all active
MeetBot instances, ensuring pending state is flushed to AlloyDB before termination.
"""

import signal
import logging
import asyncio
import sys
from typing import Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from services.stormee_meet_bot_service import MeetBot

logger = logging.getLogger(__name__)


class GracefulShutdownManager:
    """Manages graceful shutdown of MeetBot instances.
    
    Registers signal handlers for SIGTERM and SIGINT (on non-Windows platforms)
    and coordinates shutdown of all active MeetBot instances with a bounded timeout.
    """
    
    _shutdown_in_progress = False
    
    @staticmethod
    def register_shutdown_handler(
        bot_registry: Dict[str, 'MeetBot'],
        timeout_seconds: int = 30
    ) -> None:
        """Register signal handlers for graceful shutdown.
        
        Registers SIGTERM and optionally SIGINT signal handlers that will
        coordinate graceful shutdown of all active MeetBot instances.
        
        Args:
            bot_registry: Dictionary of meeting_id -> MeetBot instances.
            timeout_seconds: Maximum time (seconds) to wait for shutdown. Default: 30.
        """
        def signal_handler(signum, frame):
            """Handle shutdown signals.
            
            Iterates through all active MeetBot instances and calls graceful_shutdown()
            on each, with bounded timeout enforcement.
            """
            if GracefulShutdownManager._shutdown_in_progress:
                logger.warning(
                    "Shutdown already in progress. Ignoring duplicate signal."
                )
                return
            
            GracefulShutdownManager._shutdown_in_progress = True
            
            signal_name = signal.Signals(signum).name
            logger.info(f"Received {signal_name} signal. Starting graceful shutdown...")
            
            try:
                # Create event loop if needed
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                
                # Collect shutdown tasks for all active bots
                shutdown_tasks = []
                for meeting_id, bot in bot_registry.items():
                    try:
                        logger.info(f"Initiating graceful shutdown for meeting_id: {meeting_id}")
                        task = asyncio.ensure_future(bot.graceful_shutdown())
                        shutdown_tasks.append((meeting_id, task))
                    except Exception as e:
                        logger.error(
                            f"Failed to initiate shutdown for meeting_id {meeting_id}: {str(e)}"
                        )
                
                if shutdown_tasks:
                    # Wait for all shutdown tasks with bounded timeout
                    async def wait_all_shutdowns():
                        tasks = [task for _, task in shutdown_tasks]
                        try:
                            await asyncio.wait_for(
                                asyncio.gather(*tasks, return_exceptions=True),
                                timeout=timeout_seconds
                            )
                            logger.info(f"All bots shut down gracefully within {timeout_seconds}s")
                        except asyncio.TimeoutError:
                            logger.warning(
                                f"Shutdown timeout ({timeout_seconds}s) exceeded. "
                                f"Proceeding with forceful termination."
                            )
                            # Cancel remaining tasks
                            for _, task in shutdown_tasks:
                                if not task.done():
                                    task.cancel()
                    
                    # Run the shutdown waiter
                    try:
                        loop.run_until_complete(wait_all_shutdowns())
                    except Exception as e:
                        logger.error(
                            f"Error during shutdown task collection: {str(e)}"
                        )
                else:
                    logger.info("No active bots to shut down")
                
                logger.info("Graceful shutdown completed. Exiting...")
                sys.exit(0)
                
            except Exception as e:
                logger.error(
                    f"Critical error during graceful shutdown: {str(e)}"
                )
                sys.exit(1)
        
        # Register handlers for SIGTERM and SIGINT (SIGINT not available on Windows)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Register SIGINT handler on non-Windows platforms
        if not sys.platform.startswith('win'):
            signal.signal(signal.SIGINT, signal_handler)
        
        logger.info("Graceful shutdown handlers registered")


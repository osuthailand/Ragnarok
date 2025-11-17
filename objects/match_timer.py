"""Match countdown timer implementation for automated match starts."""

import asyncio
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from objects.match import Match


class MatchCountdownTimer:
    """Base countdown timer for multiplayer matches."""

    def __init__(self, match: "Match"):
        self.match = match
        self.running = False
        self.time_remaining = 0.0
        self.task: asyncio.Task | None = None

    @property
    def time_message(self) -> str:
        """Message format for countdown updates."""
        return "Countdown ends in {}"

    @property
    def finished_message(self) -> str:
        """Message when countdown completes."""
        return "Countdown finished"

    @property
    def aborted_message(self) -> str:
        """Message when countdown is aborted."""
        return "Countdown aborted"

    def get_time_string(self) -> str:
        """Format remaining time as a readable string."""
        minutes = int(self.time_remaining // 60)
        seconds = int(self.time_remaining % 60)

        parts = []
        if minutes > 0:
            parts.append(f"{minutes} {'minute' if minutes == 1 else 'minutes'}")
        if seconds > 0:
            parts.append(f"{seconds} {'second' if seconds == 1 else 'seconds'}")

        return " and ".join(parts) if parts else "0 seconds"

    async def start(self, duration: float):
        """Start the countdown timer."""
        await self.stop()

        self.time_remaining = duration
        from packets import writer
        self.match.enqueue(writer.notification(self.time_message.format(self.get_time_string())))

        self.running = True
        self.task = asyncio.create_task(self._run())

    async def stop(self, success: bool = False):
        """Stop the countdown timer."""
        if self.running:
            self.running = False
            if self.task and not self.task.done():
                self.task.cancel()
                try:
                    await self.task
                except asyncio.CancelledError:
                    pass

            from packets import writer
            message = self.finished_message if success else self.aborted_message
            if message:
                self.match.enqueue(writer.notification(message))

    async def _run(self):
        """Main countdown loop."""
        try:
            while self.running and self.time_remaining > 0:
                await asyncio.sleep(1)
                self.time_remaining -= 1
                await self._process_time()

            if self.running and self.time_remaining <= 0:
                await self._on_countdown_end()
        except asyncio.CancelledError:
            pass

    async def _process_time(self):
        """Process countdown tick and send announcements."""
        from packets import writer

        # Announce at specific intervals
        if (
            (self.time_remaining % 60 == 0 and self.time_remaining >= 60)  # Every minute
            or self.time_remaining == 30  # 30 seconds
            or self.time_remaining == 10  # 10 seconds
            or (1 <= self.time_remaining <= 5)  # Last 5 seconds
        ):
            self.match.enqueue(
                writer.notification(self.time_message.format(self.get_time_string()))
            )

    async def _on_countdown_end(self):
        """Called when countdown reaches zero."""
        await self.stop(success=True)


class MatchStartTimer(MatchCountdownTimer):
    """Countdown timer that automatically starts a match when it reaches zero."""

    @property
    def time_message(self) -> str:
        return "Match starts in {}"

    @property
    def finished_message(self) -> str:
        return ""  # No message, match start will announce

    async def _process_time(self):
        """Process countdown with special messages."""
        from packets import writer

        # "Good luck, have fun!" at 2 seconds
        if self.time_remaining == 2:
            self.match.enqueue(writer.notification("Good luck, have fun!"))
            return

        # Don't announce during last 2 seconds (already said good luck)
        if self.time_remaining < 2:
            return

        # Standard announcements for other times
        await super()._process_time()

    async def _on_countdown_end(self):
        """Start the match when countdown ends."""
        # Find the host player to call the start function
        host_player = None
        for slot in self.match.slots:
            if slot.player and slot.player.id == self.match.host:
                host_player = slot.player
                break

        if host_player:
            # Import here to avoid circular dependency
            from events.bancho import mp_start
            from packets.reader import Reader

            # Create empty reader since start doesn't need data from packet
            reader = Reader(b"")

            # Force start the match
            self.match.in_progress = False  # Temporarily set to allow start
            await mp_start(host_player, reader)

        await self.stop(success=True)

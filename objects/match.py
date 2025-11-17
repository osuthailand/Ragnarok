from constants.match import SlotStatus, SlotTeams, TeamType, ScoringType
from objects.channel import Channel
from objects.beatmap import Beatmap
from constants.playmode import Mode
from constants.mods import Mods
from packets import writer
from objects import services
from typing import TYPE_CHECKING, Union
import asyncio
import time

if TYPE_CHECKING:
    from objects.player import Player
    from objects.match_timer import MatchStartTimer


class Slot:
    def __init__(self):
        self.player: Union["Player", None] = None
        self.mods: Mods = Mods.NONE
        self.host: bool = False
        self.status: SlotStatus = SlotStatus.OPEN
        self.team: SlotTeams = SlotTeams.NEUTRAL
        self.loaded: bool = False
        self.skipped: bool = False

    def reset(self) -> None:
        self.player = None
        self.mods = Mods.NONE
        self.host = False
        self.status = SlotStatus.OPEN
        self.team = SlotTeams.NEUTRAL
        self.loaded = False
        self.skipped = False

    def copy_from(self, old: "Slot"):
        self.player = old.player
        self.mods = old.mods
        self.host = old.host
        self.status = old.status
        self.team = old.team
        self.loaded = old.loaded
        self.skipped = old.skipped


class Match:
    def __init__(self):
        self.id: int = 0
        self.name: str = ""
        self.password: str = ""

        self.host: int = 0
        self.in_progress: bool = False

        self.map: Beatmap | None = None

        self.slots: list[Slot] = [Slot() for _ in range(16)]

        self.mode: Mode = Mode.OSU
        self.mods: Mods = Mods.NONE
        self.freemods: bool = False

        self.scoring_type: ScoringType = ScoringType.SCORE
        self.pp_win_condition: bool = False
        self.team_type: TeamType = TeamType.HEAD2HEAD

        self.seed: int = 0

        self.connected: list["Player"] = []

        self.is_locked: bool = False

        # Thread safety lock
        self.lock: asyncio.Lock = asyncio.Lock()

        # Action timestamp tracking for idle detection
        self.last_action_time: float = time.time()

        # Match countdown timer
        self.start_timer: "MatchStartTimer | None" = None

        self.chat: Channel = Channel(
            **{
                "raw": f"#multi_{self.id}",
                "name": "#multiplayer",
                "description": self.name,
                "public": False,
                "is_temporary": True,
            }
        )

    def __repr__(self) -> str:
        return f"MATCH-{self.id}"

    @property
    def embed(self) -> str:
        return f"[osump://{self.id}/{self.password.replace(' ', '_')} {self.name}]"

    @property
    def is_idle(self) -> bool:
        """Check if match has been idle for more than 30 minutes."""
        return (time.time() - self.last_action_time) > 1800  # 30 minutes

    def get_free_slot(self) -> int | None:
        for id, slot in enumerate(self.slots):
            if slot.status == SlotStatus.OPEN:
                return id

    def find_user(self, player: "Player") -> Slot | None:
        for slot in self.slots:
            if slot.player is not None and slot.player == player:
                return slot

    def find_user_slot(self, player: "Player") -> int | None:
        for id, slot in enumerate(self.slots):
            if slot.player is not None and slot.player == player:
                return id

    def find_slot(self, slot_id: int) -> Slot | None:
        if slot_id > 16:
            return

        return self.slots[slot_id]

    def transfer_host(self, slot: Slot) -> None:
        if slot.player is None:
            return

        self.host = slot.player.id

        slot.player.enqueue(writer.match_transfer_host())
        self.enqueue(writer.notification(f"{slot.player.username} became host!"))
        self.enqueue_state()

    def enqueue_state(self, ignore: set[int] = set(), lobby: bool = False) -> None:
        for player in self.connected:
            if player.id not in ignore:
                player.enqueue(writer.match_update(self))

        if lobby:
            if not (channel := services.channels.get("#lobby")):
                return

            channel.enqueue(writer.match_update(self))

    def enqueue(self, data, lobby: bool = False) -> None:
        for player in self.connected:
            player.enqueue(data)

        if lobby:
            if not (channel := services.channels.get("#lobby")):
                return

            channel.enqueue(data)

    async def start_countdown(self, duration: float = 10.0):
        """Start a countdown timer that automatically starts the match."""
        if self.start_timer is None:
            from objects.match_timer import MatchStartTimer
            self.start_timer = MatchStartTimer(self)

        await self.start_timer.start(duration)

    async def stop_countdown(self):
        """Stop the countdown timer if running."""
        if self.start_timer and self.start_timer.running:
            await self.start_timer.stop()

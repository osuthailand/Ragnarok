from constants.match import SlotStatus, SlotTeams, TeamType, ScoringType
from objects.channel import Channel
from objects.beatmap import Beatmap
from constants.playmode import Mode
from constants.mods import Mods
from packets import writer
from objects import services
from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:
    from objects.player import Player


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
        self.match_id: int = 0
        self.match_name: str = ""
        self.match_pass: str = ""

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

        self.locked: bool = False

        self.chat: Channel = Channel(
            **{
                "raw": f"#multi_{self.match_id}",
                "name": "#multiplayer",
                "description": self.match_name,
                "public": False,
                "ephemeral": True,
            }
        )

    def __repr__(self) -> str:
        return f"MATCH-{self.match_id}"

    def get_free_slot(self) -> int:
        for id, slot in enumerate(self.slots):
            if slot.status == SlotStatus.OPEN:
                return id

        return -1

    def find_host(self) -> Slot | None:
        for slot in self.slots:
            if slot.player is not None and slot.player.id == self.host:
                return slot

    def find_user(self, p: "Player") -> Slot | None:
        for slot in self.slots:
            if slot.player == p:
                return slot

    def find_user_slot(self, p: "Player") -> int | None:
        for id, slot in enumerate(self.slots):
            if slot.player is not None and slot.player.token == p.token:
                return id

    def find_slot(self, slot_id: int) -> Slot | None:
        if slot_id > 16:
            return

        for id, slot in enumerate(self.slots):
            if id == slot_id:
                return slot

    def transfer_host(self, slot: Slot) -> None:
        if slot.player is None:
            return

        self.host = slot.player.id

        slot.player.enqueue(writer.match_transfer_host())
        self.enqueue(writer.notification(f"{slot.player.username} became host!"))
        self.enqueue_state()

    def enqueue_state(self, immune: set[int] = set(), lobby: bool = False) -> None:
        for p in self.connected:
            if p.id not in immune:
                p.enqueue(writer.match_update(self))

        if lobby:
            if not (chan := services.channels.get("#lobby")):
                return

            chan.enqueue(writer.match_update(self))

    def enqueue(self, data, lobby: bool = False) -> None:
        for p in self.connected:
            p.enqueue(data)

        if lobby:
            if not (chan := services.channels.get("#lobby")):
                return

            chan.enqueue(data)

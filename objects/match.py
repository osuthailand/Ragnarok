from constants.match import SlotStatus, SlotTeams, TeamType, ScoringType
from objects.channel import Channel
from objects.beatmap import Beatmap
from constants.playmode import Mode
from constants.mods import Mods
from packets import writer
from objects import services
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from objects.player import Player


class Players:
    def __init__(self):
        self.player: "Player" = None  # no superman :pensive:
        self.mods: Mods = Mods.NONE
        self.host: bool = False
        self.status: SlotStatus = SlotStatus.OPEN
        self.team: SlotTeams = SlotTeams.NEUTRAL
        self.loaded: bool = False
        self.skipped: bool = False

    def reset(self):
        self.player = None
        self.mods = Mods.NONE
        self.host = False
        self.status = SlotStatus.OPEN
        self.team = SlotTeams.NEUTRAL
        self.loaded = False
        self.skipped = False

    def copy_from(self, old: "Players"):
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

        self.map: Beatmap = None

        self.slots: list[Players] = [Players() for _ in range(0, 16)]

        self.mode: Mode = Mode.OSU
        self.mods: Mods = Mods.NONE
        self.freemods: bool = False

        self.scoring_type: ScoringType = ScoringType.SCORE
        self.pp_win_condition: bool = False
        self.team_type: TeamType = TeamType.HEAD2HEAD

        self.seed: int = 0

        self.connected: list["Player"] = []

        self.locked: bool = False

        self.chat: Channel = None

    def __repr__(self) -> str:
        return f"MATCH-{self.match_id}"

    def get_free_slot(self) -> int:
        for id, slot in enumerate(self.slots):
            if slot.status == SlotStatus.OPEN:
                return id

        return -1

    def find_host(self) -> Players | None:
        for slot in self.slots:
            if slot.player.id == self.host:
                return slot

    def find_user(self, p: "Player") -> Players | None:
        for slot in self.slots:
            if slot.player == p:
                return slot

    def find_user_slot(self, p: "Player") -> int | None:
        for id, slot in enumerate(self.slots):
            if slot.player == p:
                return id

    def find_slot(self, slot_id: int) -> Players | None:
        if slot_id > 16:
            return

        for id, slot in enumerate(self.slots):
            if id == slot_id:
                return slot

    def transfer_host(self, slot: Players) -> None:
        self.host = slot.player.id

        slot.player.enqueue(writer.match_transfer_host())
        self.enqueue(writer.notification(f"{slot.player.username} became host!"))
        self.enqueue_state()

    def enqueue_state(self, immune: set[int] = set(), lobby: bool = False) -> None:
        for p in self.connected:
            if p.id not in immune:
                p.enqueue(writer.match_update(self))

        if lobby:
            chan = services.channels.get("#lobby")
            assert chan is not None

            chan.enqueue(writer.match_update(self))

    def enqueue(self, data, lobby: bool = False) -> None:
        for p in self.connected:
            p.enqueue(data)

        if lobby:
            chan = services.channels.get("#lobby")
            assert chan is not None

            chan.enqueue(data)

from enum import IntEnum, unique


@unique
class SlotStatus(IntEnum):
    OPEN = 1
    LOCKED = 2
    NOTREADY = 4
    READY = 8
    NOMAP = 16
    PLAYING = 32
    COMPLETE = 64
    QUIT = 128

    @property
    def is_occupied(self) -> bool:
        return self in (
            self.NOTREADY,
            self.READY,
            self.NOMAP,
            self.PLAYING,
            self.COMPLETE,
        )


@unique
class SlotTeams(IntEnum):
    NEUTRAL = 0
    BLUE = 1
    RED = 2


@unique
class TeamType(IntEnum):
    HEAD2HEAD = 0
    TAG_COOP = 1
    TEAM_VS = 2
    TAG_TV = 3  # tag team vs


@unique
class ScoringType(IntEnum):
    SCORE = 0
    ACC = 1
    COMBO = 2
    SCORE_V2 = 3

    @classmethod
    def find_value(cls, name: str) -> "ScoringType":
        c = cls(0)

        if name == "sv2":
            return c.__class__.SCORE_V2

        if name.upper() in c.__class__.__dict__:
            return c.__class__.__dict__[name.upper()]

        return c

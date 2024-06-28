from enum import unique, IntEnum


@unique
class Mode(IntEnum):
    NONE = -1

    OSU = 0
    TAIKO = 1
    CATCH = 2
    MANIA = 3

    def __iter__(self):
        return iter((self.OSU, self.TAIKO, self.CATCH, self.MANIA))

    @classmethod
    def from_str(cls, mode: str) -> "Mode":
        match mode.lower():
            case "std" | "osu":
                return cls.OSU
            case "taiko":
                return cls.TAIKO
            case "ctb" | "catch":
                return cls.CATCH
            case "mania":
                return cls.MANIA
            case _:
                return cls.NONE

    def to_string(self) -> str:
        match self.name:
            case "OSU":
                return "osu!std"
            case "TAIKO":
                return "osu!taiko"
            case "CATCH":
                return "osu!catch"
            case "MANIA":
                return "osu!mania"
            case _:
                return "undefined"

    def to_db(self, s: str) -> str:
        match self.name:
            case "OSU":
                return s + "_std as " + s
            case "TAIKO":
                return s + "_taiko as " + s
            case "CATCH":
                return s + "_catch as " + s
            case "MANIA":
                return s + "_mania as " + s
            case _:
                return "undefined"


@unique
class Gamemode(IntEnum):
    UNKNOWN = -1

    VANILLA = 0
    RELAX = 1

    @property
    def table(self):
        return (
            "stats"
            if self == self.VANILLA
            else "stats_rx" if self == self.RELAX else "error"
        )

    @property
    def score_order(self):
        return "score" if self == self.VANILLA else "pp"

    @classmethod
    def from_str(cls, s: str) -> "Gamemode":
        match s:
            case "vn" | "vanilla":
                return cls.VANILLA
            case "rx" | "relax":
                return cls.RELAX
            case _:
                return cls.UNKNOWN

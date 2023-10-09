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
    def from_str(cls, mode: str):
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
                return s + "_std"
            case "TAIKO":
                return s + "_taiko"
            case "CATCH":
                return s + "_catch"
            case "MANIA":
                return s + "_mania"
            case _:
                return "undefined"

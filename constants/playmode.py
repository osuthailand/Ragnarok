from enum import unique, IntEnum


@unique
class Mode(IntEnum):
    NONE = -1

    OSU = 0
    TAIKO = 1
    CATCH = 2
    MANIA = 3

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

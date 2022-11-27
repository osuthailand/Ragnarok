from enum import unique, IntEnum


@unique
class Mode(IntEnum):
    NONE = -1

    OSU = 0
    TAIKO = 1
    CATCH = 2
    MANIA = 3

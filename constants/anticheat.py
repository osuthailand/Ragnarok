from enum import IntFlag, unique


# do later
@unique
class BadFlags(IntFlag):
    INVALID_MOD_COMBO = 4
    HWID_SANITY = 16

    # "Couldn't load flashlight" (texture got deleted/modified)
    INVALID_FLASHLIGHT = 256

    SPINNER = 512

    TOO_FAST_MANIA = 2048
    AIM_ASSIST = 4096

    RELAX = 120843213

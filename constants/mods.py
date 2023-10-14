from enum import IntFlag
from utils import log


class Mods(IntFlag):
    NONE = 0
    NOFAIL = 1
    EASY = 2
    TOUCHDEVICE = 4
    HIDDEN = 8
    HARDROCK = 16
    SUDDENDEATH = 32
    DOUBLETIME = 64
    RELAX = 128
    HALFTIME = 256
    NIGHTCORE = 512
    FLASHLIGHT = 1024
    AUTOPLAY = 2048
    SPUNOUT = 4096
    RELAX2 = 8192
    PERFECT = 16384
    KEY4 = 32768
    KEY5 = 65536
    KEY6 = 131072
    KEY7 = 262144
    KEY8 = 524288
    FADEIN = 1048576
    RANDOM = 2097152
    CINEMA = 4194304
    TARGET = 8388608
    KEY9 = 16777216
    KEYCOOP = 33554432
    KEY1 = 67108864
    KEY3 = 134217728
    KEY2 = 268435456
    SCOREV2 = 536870912
    LASTMOD = 1073741824
    KEYMOD = KEY1 | KEY2 | KEY3 | KEY4 | KEY5 | KEY6 | KEY7 | KEY8 | KEY9 | KEYCOOP
    FREEMODALLOWED = (
        NOFAIL
        | EASY
        | HIDDEN
        | HARDROCK
        | SUDDENDEATH
        | FLASHLIGHT
        | FADEIN
        | RELAX
        | RELAX2
        | SPUNOUT
        | KEYMOD
    )
    SCOREINCREASEMODS = HIDDEN | HARDROCK | DOUBLETIME | FLASHLIGHT | FADEIN

    MULTIPLAYER = DOUBLETIME | NIGHTCORE | HALFTIME

    DISABLED = RELAX2 | CINEMA | TARGET | AUTOPLAY

    def __dict__(self) -> dict["Mods", str]:
        return {
            self.NONE: "NM",
            self.NOFAIL: "NF",
            self.EASY: "EZ",
            self.TOUCHDEVICE: "TD",
            self.HIDDEN: "HD",
            self.HARDROCK: "HR",
            self.SUDDENDEATH: "SD",
            self.DOUBLETIME: "DT",
            self.RELAX: "RX",
            self.HALFTIME: "HT",
            self.NIGHTCORE: "NC",
            self.FLASHLIGHT: "FL",
            self.AUTOPLAY: "AU",
            self.SPUNOUT: "SO",
            self.RELAX2: "AP",
            self.PERFECT: "PF",
            self.KEY1: "1K",
            self.KEY2: "2K",
            self.KEY3: "3K",
            self.KEY4: "4K",
            self.KEY5: "5K",
            self.KEY6: "6K",
            self.KEY7: "7K",
            self.KEY8: "8K",
            self.KEY9: "9K",
            self.FADEIN: "FI",
            self.RANDOM: "RN",
            self.CINEMA: "CN",
            self.TARGET: "TP",
            self.KEYCOOP: "CO",
            self.SCOREV2: "V2",
        }

    @classmethod
    def from_str(cls, s: str) -> "Mods":
        # split every 2nd character
        mods = cls.NONE
        str_mods = [(s[i: i + 2]) for i in range(0, len(s), 2)]

        for mod in str_mods:
            for key, value in mods.__dict__().items():
                if value == mod.upper():
                    mods |= key
                    break
            else:
                log.fail(f"Mod: {mod} doesn't exist.")

        return mods

from enum import IntEnum


class Approved(IntEnum):
    GRAVEYARD = -2
    WIP = -1
    PENDING = 0

    UPDATE = 1
    RANKED = 2
    APPROVED = 3
    QUALIFIED = 4
    LOVED = 5

    @property
    def has_leaderboard(self) -> bool:
        return self.value in (self.RANKED, self.APPROVED, self.QUALIFIED, self.LOVED)

    @property
    def awards_pp(self) -> bool:
        return self.value in (self.RANKED, self.APPROVED)

    @property
    def to_osu(self) -> int:
        return {
            self.GRAVEYARD: 0,
            self.PENDING: 0,
            self.UPDATE: 1,
            self.RANKED: 2,
            self.APPROVED: 3,
            self.QUALIFIED: 4,
            self.LOVED: 5,
        }[self]

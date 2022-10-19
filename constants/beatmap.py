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

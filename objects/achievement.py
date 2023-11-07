from dataclasses import dataclass

from constants.playmode import Gamemode, Mode


@dataclass(kw_only=True)
class Achievement:
    id: int = 0
    name: str = ""
    description: str = ""
    icon: str = ""
    condition: str = ""

    def __repr__(self) -> str:
        return f"{self.icon}+{self.name}+{self.description}"


@dataclass(kw_only=True)
class UserAchievement(Achievement):
    gamemode: Gamemode = Gamemode.VANILLA
    mode: Mode = Mode.OSU

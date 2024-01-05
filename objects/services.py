import os
import re
import sys
import tomllib


from typing import Any, Pattern, TYPE_CHECKING

from attr import dataclass
from dynaconf import Dynaconf
from redis import asyncio as aioredis

from lib.database import Database
from objects.achievement import Achievement
from utils import log

if TYPE_CHECKING:
    from objects.collections import Tokens, Channels, Matches, Beatmaps
    from packets.reader import Packet
    from objects.bot import Bot

if not os.path.exists("config.toml"):
    os.rename("config.example.toml", "config.toml")
    log.warn("You have to edit the config.toml!")
    sys.exit(1)

config: Dynaconf = Dynaconf(settings_files=["config.toml"])

debug: bool = config.server.debug
domain: str = config.server.domain
port: int = config.server.port

packets: dict[int, "Packet"] = {}

bot: "Bot"

prefix: str = "!"


@dataclass
class SettingField(object):
    value: bool
    string: str = ""


class OsuSettings:
    def __init__(self) -> None:
        self.allow_game_registration = SettingField(False)
        self.server_maintenance = SettingField(False)
        self.welcome_message = SettingField(False)
        self.osu_menu_icon = SettingField(False)

    async def initialize_from_db(self) -> None:
        async for setting in sql.iterall(
            "SELECT name, boolean_value, string_value FROM osu_settings"
        ):
            if hasattr(self, setting["name"]):
                attr: SettingField = getattr(self, setting["name"])

                update = (
                    attr.value != bool(setting["boolean_value"])
                    or attr.string != setting["string_value"]
                )

                if update:
                    setattr(
                        self,
                        setting["name"],
                        SettingField(
                            value=bool(setting["boolean_value"]),
                            string=setting["string_value"],
                        ),
                    )


osu_settings: OsuSettings = OsuSettings()

sql: Database
redis: aioredis.Redis

bcrypt_cache: dict[str, bytes] = {}

# title card - james a. janisse
title_card: str = '''
                . . .o .. o
                    o . o o.o
                        ...oo.
                   ________[]_
            _______|_o_o_o_o_o\\___
            \\""""""""""""""""""""/
             \\ ...  .    . ..  ./
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
osu!ragnarok, an osu!bancho & /web/ emulator.
Authored by Simon & Aoba
'''


players: "Tokens"
channels: "Channels"
matches: "Matches"
beatmaps: "Beatmaps"

osu_key: str = config.api.key

achievements: list[Achievement] = []


def get_achievement_by_id(id: int) -> Achievement | None:
    for ach in achievements:
        if ach.id == id:
            return ach


regex: dict[str, Pattern[str]] = {
    "np": re.compile(
        rf"\x01ACTION is (?:listening to|editing|playing|watching) \[https://osu.{domain}/beatmapsets/[0-9].*#/(\d*)"
    ),
    ".osu": re.compile(r"(.*) - (.*) \((.*)\) \[(.*)\].osu"),
}

# {token: "message"}
await_response: dict[str, str] = {}

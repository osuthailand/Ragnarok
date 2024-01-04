import re

from typing import Any, Pattern, TYPE_CHECKING
from config import conf
from redis import asyncio as aioredis

from lib.database import Database
from objects.achievement import Achievement

if TYPE_CHECKING:
    from objects.collections import Tokens, Channels, Matches, Beatmaps
    from packets.reader import Packet
    from objects.bot import Bot


debug: bool = conf["server"]["debug"]
domain: str = conf["server"]["domain"]
port: int = conf["server"]["port"]

packets: dict[int, "Packet"] = {}

bot: "Bot"

prefix: str = "!"

config: dict[str, dict[str, Any]] = conf

# TODO: refactor this piece of shit
# from database
osu_settings: dict[str, dict[str, int | str]] = {}

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

osu_key: str = config["api_conf"]["osu_api_key"]

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

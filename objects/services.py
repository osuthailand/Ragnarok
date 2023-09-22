from typing import Any, Callable, Pattern, TYPE_CHECKING
from lenhttp import Router, LenHTTP
from lib.database import Database
from config import conf
from redis import asyncio as aioredis
import re

from objects.achievement import Achievement

if TYPE_CHECKING:
    from objects.collections import Tokens, Channels, Matches
    from objects.beatmap import Beatmap
    from objects.player import Player
    from packets.reader import Packet


server: LenHTTP

debug: bool = conf["server"]["debug"]
domain: str = conf["server"]["domain"]
port: int = conf["server"]["port"]

bancho: Router
avatar: Router
osu: Router

packets: dict[int, "Packet"] = {}

bot: "Player"

prefix: str = "!"

config: dict[str, dict[str, Any]] = conf

sql: Database
redis: aioredis.Redis

bcrypt_cache: dict[str, bytes] = {}

title_card: str = '''
                . . .o .. o
                    o . o o.o
                        ...oo.
                   ________[]_
            _______|_o_o_o_o_o\___
            \\""""""""""""""""""""/
             \ ...  .    . ..  ./
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
osu!ragnarok, an osu!bancho & /web/ emulator.
Authored by Simon & Aoba
'''


players: "Tokens"
channels: "Channels"
matches: "Matches"

osu_key: str = config["api_conf"]["osu_api_key"]

beatmaps: dict[str, "Beatmap"] = {}
achievements: set[Achievement] = set()

regex: dict[str, Pattern[str]] = {
    "np": re.compile(
        rf"\x01ACTION is (?:listening|editing|playing|watching) to \[https://osu.{domain}/beatmapsets/[0-9].*#/(\d*)"
    )
}

# {token: "message"}
await_response: dict[str, str] = {}

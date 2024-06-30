import logging
import re
import time
import settings


from typing import Pattern, TYPE_CHECKING

from dataclasses import dataclass
from databases import Database
from redis import asyncio as aioredis

from objects.achievement import Achievement

from colorama import Fore, Style

if TYPE_CHECKING:
    from objects.collections import Tokens, Channels, Matches, Beatmaps
    from packets.reader import Packet
    from objects.bot import Bot


debug = bool(settings.SERVER_DEBUG)
domain = settings.SERVER_DOMAIN
port = int(settings.SERVER_PORT)
startup = time.time()

packets: dict[int, "Packet"] = {}

bot: "Bot"

prefix: str = "!"
database: Database = Database(
    f"mysql+aiomysql://{settings.DB_USER}:{settings.DB_PASSWORD}@{settings.DB_HOST}/{settings.DB_DATABASE}"
)
redis: aioredis.Redis = aioredis.from_url(
    f"redis://{settings.REDIS_USERNAME}:{settings.REDIS_PASSWORD}@{settings.REDIS_HOST}:{settings.REDIS_PORT}",
    decode_responses=True,
)

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

osu_key: str = settings.OSU_API_KEY

regex: dict[str, Pattern[str]] = {
    "np": re.compile(
        rf"\x01ACTION is (?:listening to|editing|playing|watching) \[https://osu.{domain}/beatmapsets/[0-9].*#/(\d*)"
    ),
    ".osu": re.compile(r"(.*) - (.*) \((.*)\) \[(.*)\]\.osu"),
}

# {token: "message"}
await_response: dict[str, str] = {}

ALLOWED_BUILDS: list[str] = []

logger = logging.getLogger(__name__)


class Formatting(logging.Formatter):
    level_colors = {
        logging.WARNING: Fore.YELLOW,
        logging.DEBUG: Fore.GREEN,
        logging.INFO: Fore.BLUE,
        logging.ERROR: Fore.RED,
        logging.CRITICAL: Style.BRIGHT + Fore.RED,
    }

    template: str = (
        Style.DIM
        + "[%(asctime)s] | "
        + Style.RESET_ALL
        + "{level}"
        + "%(levelname)-8s"
        + Fore.RESET
        + Style.DIM
        + " | ["
        + Style.RESET_ALL
        + Fore.CYAN
        + "%(filename)s:%(funcName)s():%(lineno)s"
        + Fore.RESET
        + Style.RESET_ALL
        + Style.DIM
        + "] "
        + Style.RESET_ALL
        + "%(message)s"
    )

    def format(self, record):
        log_color = self.level_colors[record.levelno]

        formatter = logging.Formatter(
            self.template.format(level=log_color), datefmt="%H:%M:%S"
        )

        return formatter.format(record)


handler = logging.StreamHandler()
handler.setFormatter(Formatting())

logger.addHandler(handler)


@dataclass
class SettingField(object):
    value: bool
    string: str = ""


class OsuSettings:
    def __init__(self) -> None:
        self.allow_ingame_registration = SettingField(False)
        self.server_maintenance = SettingField(False)
        self.welcome_message = SettingField(False)

    async def initialize_from_db(self) -> None:
        settings = await database.fetch_all(
            "SELECT name, boolean_value, string_value FROM osu_settings"
        )

        for setting in settings:
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

achievements: list[Achievement] = []


def get_achievement_by_id(id: int) -> Achievement | None:
    for ach in achievements:
        if ach.id == id:
            return ach

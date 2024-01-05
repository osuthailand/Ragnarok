import asyncio
import time
import aiohttp
import uvicorn

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.routing import Host

from objects.achievement import Achievement
from objects.channel import Channel
from objects.collections import Tokens, Channels, Matches, Beatmaps

# routers
from events.bancho import bancho
from events.osu import osu
from events.avatar import avatar
from events.api import api

from events import map  # don't remove

# dont remove
from constants import commands

from lib.database import Database
from objects.bot import Bot
from objects import services
from utils import log
from redis import asyncio as aioredis

import os
import tasks


REQUIRED_DIRECTORIES = (
    ".data/avatars",
    ".data/replays",
    ".data/beatmaps",
    ".data/ss",
    ".data/osz2",
)


async def startup() -> None:
    print(f"\033[94m{services.title_card}\033[0m")

    services.players = Tokens()
    services.channels = Channels()
    services.matches = Matches()
    services.beatmaps = Beatmaps()

    for _path in REQUIRED_DIRECTORIES:
        if not os.path.exists(_path):
            log.warn(
                f"You're missing the folder {_path}! Don't worry we'll add it for you!"
            )

            os.makedirs(_path)

    log.info(f"Running Ragnarok on `{services.domain}` (port: {services.port})")
    log.info("... Connecting to the database")

    services.sql = Database()
    await services.sql.connect(services.config.database)

    log.info("✓ Connected to the database!")
    log.info("... Initalizing redis")

    redisconf = services.config.redis
    services.redis = aioredis.from_url(
        f"redis://{redisconf.username}:{redisconf.password}@{redisconf.host}:{redisconf.port}"
    )
    await services.redis.initialize()

    log.info("✓ Successfully initalized redis")
    log.info("... Connecting Louise to the server")

    await Bot.initialize()

    log.info("✓ Successfully connected Louise!")

    log.info("... Caching required data")
    await tasks.run_cache_task()
    log.info("✓ Finished caching everything needed!")

    log.info("... Starting background tasks")

    asyncio.create_task(tasks.run_all_tasks())

    log.info("✓ Successfully started all background tasks")
    log.info("Finished up connecting to everything!")


async def not_found(req: Request, exc: HTTPException) -> Response:
    log.fail(f"[{req.method}] {req.url._url[8:]} not found")
    return Response(content=exc.detail.encode(), status_code=404)


app = Starlette(
    routes=[
        Host(f"c.{services.domain}", bancho),
        Host(f"c4.{services.domain}", bancho),
        Host(f"osu.{services.domain}", osu),
        Host(f"a.{services.domain}", avatar),
        Host(f"api.{services.domain}", api),
    ],
    on_startup=[startup],
    exception_handlers={404: not_found},  # type: ignore
)

if __name__ == "__main__":
    uvicorn.run(
        "server:app",
        host="127.0.0.1",
        port=services.port,
        log_level="error",
        loop="uvloop",
    )

import asyncio
import uvicorn

from starlette.applications import Starlette
from starlette.routing import Host

from objects.achievement import Achievement
from objects.collections import Tokens, Channels, Matches

# routers
from events.bancho import bancho
from events.osu import osu
from events.avatar import avatar
from events.api import api

# dont remove
from constants import commands

from lib.database import Database
from objects.bot import Bot
from objects import services
from utils import log
from redis import asyncio as aioredis

import os
import sys
import tasks


async def startup():
    print(f"\033[94m{services.title_card}\033[0m")

    services.players = Tokens()
    services.channels = Channels()
    services.matches = Matches()

    for _path in (".data/avatars", ".data/replays", ".data/beatmaps", ".data/ss"):
        if not os.path.exists(_path):
            log.warn(
                f"You're missing the folder {_path}! Don't worry we'll add it for you!"
            )

            os.makedirs(_path)

    log.info(f"Running Ragnarok on `{services.domain}` (port: {services.port})")
    log.info(".. Connecting to the database")

    services.sql = Database()
    await services.sql.connect(services.config["mysql"])

    log.info("✓ Connected to the database!")
    log.info(".. Initalizing redis")

    redisconf = services.config["redis"]
    services.redis = aioredis.from_url(
        f"redis://{redisconf['username']}:{redisconf['password']}@{redisconf['host']}:{redisconf['port']}"
    )
    await services.redis.initialize()

    log.info("✓ Successfully initalized redis")
    log.info("... Connecting Louise to the server")

    if not await Bot.init():
        log.fail("✗ Couldn't find Louise in the database.")
        sys.exit()

    log.info("✓ Successfully connected Louise!")
    log.info("... Adding channels")

    async for channel in services.sql.iterall(
        "SELECT name, description, public, staff, auto_join, read_only FROM channels"
    ):
        services.channels.add(channel)

    log.info("✓ Successfully added all avaliable channels")
    log.info("... Caching achievements")

    async for achievement in services.sql.iterall("SELECT * FROM achievements"):
        services.achievements.add(Achievement(**achievement))

    log.info("✓ Successfully cached all achievements")

    log.info("... Starting background tasks")
    asyncio.create_task(tasks.run_all_tasks())
    log.info("✓ Successfully started all background tasks")

    log.info("Finished up connecting to everything!")


app = Starlette(
    routes=[
        Host(f"c.{services.domain}", bancho),
        Host(f"c4.{services.domain}", bancho),
        Host(f"osu.{services.domain}", osu),
        Host(f"a.{services.domain}", avatar),

        Host(f"api.{services.domain}", api)
    ],
    on_startup=[startup],
)

if __name__ == "__main__":
    uvicorn.run("server:app", host="127.0.0.1", port=services.port, log_level="error", loop="uvloop")


# @avatar.avatar.after_request()
# @osu.osu.after_request()
# async def after_request(req: Request):
#     if req.resp_code == 404:
#         lprint = log.error
#     else:
#         lprint = log.info

#     lprint(f"[{req.type}] {req.path} | {req.elapsed}")


# @services.server.add_middleware(500)
# async def fivehundred(req: Request, tb: str):
#     log.fail(f"An error occured on `{req.path}` | {req.elapsed}\n{tb}")

#     return b""


# if __name__ == "__main__":
#     services.server.add_routers({bancho.bancho, avatar.avatar, osu.osu})
#     services.server.start()

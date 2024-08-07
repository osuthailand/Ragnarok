import asyncio
import logging
import aiohttp
import uvicorn
import settings

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.routing import Host

from objects.collections import Tokens, Channels, Matches, Beatmaps

# routers
from events.bancho import bancho
from events.osu import osu

from events import map  # don't remove

# dont remove
from constants import commands

from objects.bot import Bot
from objects import services

import os
import tasks


REQUIRED_DIRECTORIES = (
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

    services.loop = asyncio.get_running_loop()
    services.http_client_session = aiohttp.ClientSession(loop=services.loop)

    services.logger.setLevel(logging.DEBUG if settings.SERVER_DEBUG else logging.INFO)

    for _path in REQUIRED_DIRECTORIES:
        if not os.path.exists(_path):
            services.logger.warn(
                f"You're missing the folder {_path}! Don't worry we'll add it for you!"
            )

            os.makedirs(_path)

    services.logger.info(
        f"Running Ragnarok on `{services.domain}` (port: {services.port})"
    )

    services.logger.info("... Connecting to the database")
    await services.database.connect()
    services.logger.info("✓ Connected to the database!")

    services.logger.info("... Initalizing redis")
    await services.redis.initialize()
    services.logger.info("✓ Successfully initalized redis")

    services.logger.info("... Connecting the bot to the server")
    await Bot.initialize()
    services.logger.info("✓ Successfully connected Louise!")

    services.logger.info("... Caching required data")
    await tasks.run_cache_task()
    services.logger.info("✓ Finished caching everything needed!")

    services.logger.info("... Starting background tasks")
    services.loop.create_task(tasks.run_all_tasks())
    services.logger.info("✓ Successfully started all background tasks")

    services.logger.info("Finished up connecting to everything!")


async def shutdown() -> None:
    services.logger.info(
        "... Disconnecting from redis, aiohttp's client session, and the database."
    )
    await services.database.disconnect()
    await services.redis.aclose()
    await services.http_client_session.close()
    services.logger.info("✓ Successfully disconnected.")


async def not_found(req: Request, exc: HTTPException) -> Response:
    services.logger.debug(f"[{req.method}] {req.url._url[8:]} not found")
    return Response(content=exc.detail.encode(), status_code=404)


app = Starlette(
    routes=[
        Host(f"c.{services.domain}", bancho),
        Host(f"c4.{services.domain}", bancho),
        Host(f"osu.{services.domain}", osu),
    ],
    on_startup=[startup],
    on_shutdown=[shutdown],
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

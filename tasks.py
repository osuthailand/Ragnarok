from dataclasses import dataclass
from typing import Callable

from objects import services
from objects.achievement import Achievement
from objects.channel import Channel


import time
import asyncio


TOKEN_EXPIRATION = 30  # seconds


@dataclass
class Task:
    cb: Callable
    delay: int
    last_called: float


tasks: list[Task] = []


def register_task(delay: int) -> Callable:
    def decorator(cb: Callable) -> None:
        tasks.append(Task(cb=cb, delay=delay, last_called=time.time()))

    return decorator


@register_task(delay=5)
async def removed_expired_tokens() -> None:
    for player in services.players:
        # doesn't look like afk players get the afk thingy thing thing
        # ^^^ bro what?
        if time.time() - player.last_update >= TOKEN_EXPIRATION and not player.is_bot:
            await player.logout()
            services.logger.info(
                f"{player.username} has been logged out, due to loss of connection."
            )


@register_task(delay=60)
async def check_for_osu_settings_update() -> None:
    await services.osu_settings.initialize_from_db()


async def run_all_tasks() -> None:
    while True:
        for task in tasks:
            if time.time() - task.last_called >= task.delay:
                await task.cb()

                task.last_called = time.time()

        await asyncio.sleep(0.1)


ALLOWED_STREAMS = ("stable40", "cuttingedge", "beta")


# pretty ugly
async def cache_allowed_osu_builds() -> None:
    versions = []

    response = await services.http_client_session.get(
        "https://osu.ppy.sh/api/v2/changelog"
    )
    decoded = await response.json()

    for stream in decoded["streams"]:
        if stream["name"] not in ALLOWED_STREAMS:
            continue

        match stream["name"]:
            case "beta40":
                suffix = "beta"
            case "cuttingedge":
                suffix = "cuttingedge"
            case _:
                suffix = ""

        versions.append(stream["latest_build"]["version"] + suffix)

    for build in decoded["builds"]:
        if build["update_stream"]["name"] not in ALLOWED_STREAMS:
            continue

        match build["update_stream"]["name"]:
            case "beta40":
                suffix = "beta"
            case "cuttingedge":
                suffix = "cuttingedge"
            case _:
                suffix = ""

        versions.append(build["version"] + suffix)

    services.ALLOWED_BUILDS = versions


async def cache_channels() -> None:
    channels = await services.database.fetch_all(
        "SELECT name, description, public, staff, auto_join, read_only FROM channels"
    )

    for channel_db in channels:
        channel = Channel(**dict(channel_db))
        services.channels.add(channel)


async def cache_achievements() -> None:
    achievements = await services.database.fetch_all("SELECT * FROM achievements")

    for achievement in achievements:
        services.achievements.append(Achievement(**dict(achievement)))


async def run_cache_task() -> None:
    await asyncio.gather(
        *[
            cache_allowed_osu_builds(),
            cache_achievements(),
            cache_channels(),
            services.osu_settings.initialize_from_db(),
        ]
    )

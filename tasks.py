from dataclasses import dataclass
from typing import Callable
from constants.player import bStatus
from objects import services
from utils import log

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


@register_task(delay=1)
async def removed_expired_tokens() -> None:
    for player in services.players:
        # doesn't look like afk players get the afk thingy thing thing
        # ^^^ bro what?
        if (
            time.time() - player.last_update >= TOKEN_EXPIRATION
            and not player.bot
            and player.status != bStatus.AFK
        ):
            player.logout()
            log.info(
                f"{player.username} has been logged out, due to loss of connection."
            )


@register_task(delay=60)
async def check_for_osu_settings_update() -> None:
    await services.osu_settings.initialize_from_db()


async def run_all_tasks():
    while True:
        for task in tasks:
            if time.time() - task.last_called >= task.delay:
                await task.cb()

                task.last_called = time.time()

        await asyncio.sleep(0.1)

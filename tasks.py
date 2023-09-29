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
        if (
            time.time() - player.last_update >= TOKEN_EXPIRATION
            and not player.bot
            and player.status != bStatus.AFK
        ):
            await player.logout()
            log.info(
                f"{player.username} has been logged out, due to loss of connection."
            )


# @register_task(delay=300)
# async def delete_pending_accounts() -> None:
#     async for channel in services.sql.iterall(
#         "SELECT 1 FROM users WHERE privileges = "
#     )


async def run_all_tasks():
    while True:
        for task in tasks:
            if time.time() - task.last_called >= task.delay:
                await task.cb()

                task.last_called = time.time()

        await asyncio.sleep(0.1)

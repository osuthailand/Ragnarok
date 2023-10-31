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
            player.logout()
            log.info(
                f"{player.username} has been logged out, due to loss of connection."
            )


@register_task(delay=60)
async def check_for_osu_settings_update() -> None:
    async for setting in services.sql.iterall("SELECT * FROM osu_settings"):
        setting_data = {key: value for key, value in setting.items() if key != "name"}

        if setting["name"] not in services.osu_settings:
            services.osu_settings["name"] = setting_data

        for setting_key, setting_value in services.osu_settings.items():
            if setting["name"] != setting_key:
                continue

            if setting_value != setting_data:
                services.osu_settings[setting_key] = setting_data
                log.debug(f"Detected a change in {setting_key} and have updated it.")


async def run_all_tasks():
    while True:
        for task in tasks:
            if time.time() - task.last_called >= task.delay:
                await task.cb()

                task.last_called = time.time()

        await asyncio.sleep(0.1)

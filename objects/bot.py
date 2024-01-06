import asyncio
from datetime import datetime
import sys
from constants.anticheat import BadFlags
from constants.player import bStatus
from objects.score import Score
from packets import writer
from objects import services

import discord

from objects.player import Player


class Bot(Player):
    def __init__(self, *args):
        super().__init__(*args)

        self.discord: discord.Client

    @classmethod
    async def initialize(cls) -> "Bot":
        if not (
            bot := await services.sql.fetch(
                "SELECT id, username, privileges, passhash FROM users WHERE id = 1"
            )
        ):
            services.logger.critical(f"✗ Couldn't find the bot in the database.")
            sys.exit()

        bot = cls(bot["username"], bot["id"], bot["privileges"], bot["passhash"])

        bot.status = bStatus.WATCHING
        bot.status_text = "over scores"

        bot.bot = True

        intents = discord.Intents.default()
        bot.discord = discord.Client(intents=intents)

        try:
            await bot.discord.login(services.config.discord.token)
        except discord.LoginFailure:
            services.logger.critical(
                "✗ Failed to login into discord bot (invalid token)."
            )
            sys.exit()

        services.bot = bot
        services.players.add(bot)
        services.players.enqueue(writer.bot_presence() + writer.update_stats(bot))

        return bot

    async def anticheat_log(
        self,
        score: Score,
        flag: BadFlags,
        description: str,
        title: str = "Unsual score",
    ) -> None:
        await self.log(f"has caugth {score.player.username} triggering the anticheat")

        await services.sql.execute(
            "INSERT INTO anticheat (user_id, bad_flag) VALUES (%s, %s)",
            (score.player.id, flag),
        )

        flag_count = await services.sql.fetch(
            "SELECT COUNT(*) AS count FROM anticheat WHERE user_id = %s",
            (score.player.id),
        )

        GUILD_ID = 483250302800101376
        CHANNEL = 1187927246518878250

        guild = await self.discord.fetch_guild(GUILD_ID)
        assert guild is not None

        channel = await guild.fetch_channel(CHANNEL)
        assert channel is not None

        embed = discord.Embed(
            title=title,
            url=f"https://rina.place/score/{score.id}",
            description=description,
            colour=0xF50018,
            timestamp=datetime.now(),
        )

        embed.set_author(
            name=f"{score.player.username} (ID: {score.player.id})",
            url=f"https://rina.place/u/{score.player.id}",
            icon_url=f"https://a.rina.place/u/{score.player.id}",
        )

        embed.add_field(name="Flag", value=f"``{flag.name}``", inline=True)
        embed.add_field(name="Flag count", value=flag_count["count"], inline=True)
        embed.add_field(name="Priority", value="**not implemented**", inline=True)

        embed.set_thumbnail(
            url=f"https://assets.ppy.sh/beatmaps/{score.map.set_id}/covers/list.jpg"
        )

        embed.set_footer(
            text="Ragnarok - Anticheat",
            icon_url="https://cdn.discordapp.com/avatars/1187921718338130061/0f2f0833755a8e59b46ef4df380e837e.webp",
        )

        await channel.send(embed=embed)

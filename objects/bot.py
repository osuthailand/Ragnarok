import sys
from constants.player import bStatus
from packets import writer
from objects import services

from objects.player import Player


class Bot(Player):
    def __init__(self, *args):
        super().__init__(*args)

    @classmethod
    async def initialize(cls) -> "Bot":
        if not (
            bot := await services.database.fetch_one(
                "SELECT id, username, privileges, passhash FROM users WHERE id = 1"
            )
        ):
            services.logger.critical(f"✗ Couldn't find the bot in the database.")
            sys.exit()

        bot = cls(bot["username"], bot["id"], bot["privileges"], bot["passhash"])

        bot.status = bStatus.WATCHING
        bot.status_text = "over scores"

        bot.bot = True

        services.bot = bot
        services.players.add(bot)
        services.players.enqueue(writer.bot_presence() + writer.update_stats(bot))

        return bot

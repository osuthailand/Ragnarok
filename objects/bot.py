from objects.player import Player
from constants.player import bStatus
from packets import writer
from objects import services


class Bot:
    @staticmethod
    async def init() -> bool:
        if not (
            bot := await services.sql.fetch(
                "SELECT id, username, privileges, passhash FROM users WHERE id = 1"
            )
        ):
            return False

        p = Player(bot["username"], bot["id"], bot["privileges"], bot["passhash"])

        p.status = bStatus.WATCHING
        p.status_text = "over deez nutz"

        p.bot = True

        services.bot = p

        services.players.add(p)

        for player in services.players.players:
            player.enqueue(await writer.UserPresence(p) + await writer.UpdateStats(p))

        return True

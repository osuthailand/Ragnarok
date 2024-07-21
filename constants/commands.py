import copy
import os
import signal
import sys
import random
import traceback
import settings

from objects.achievement import UserAchievement
from objects.beatmap import Beatmap
from objects.match import Match
from objects.score import SubmitStatus

from typing import Union
from packets import writer
from typing import Callable
from objects import services
from dataclasses import dataclass
from rina_pp_pyb import Beatmap as BMap, GameMode, Performance

from objects.bot import Bot
from constants.mods import Mods
from constants.playmode import Gamemode, Mode
from constants.player import Privileges
from constants.packets import ServerPackets
from constants.match import SlotStatus, ScoringType

from objects.channel import Channel
from objects.player import LoggingType, Player


from functools import wraps


@dataclass
class Context:
    author: Player
    reciever: Channel | Player

    cmd: str
    args: list[str]


@dataclass
class Command:
    trigger: Callable
    cmd: str
    aliases: list[str]

    perms: Privileges
    doc: str | None
    category: str
    hidden: bool


commands: list["Command"] = []
mp_commands: list["Command"] = []


def register_mp_command(
    trigger: str,
    required_perms: Privileges = Privileges.USER,
    hidden: bool = False,
    aliases: list[str] = [],
):
    def decorator(cb: Callable) -> None:
        cmd = Command(
            trigger=cb,
            cmd=trigger,
            aliases=aliases,
            perms=required_perms,
            doc=cb.__doc__,
            hidden=hidden,
            category="Multiplayer",
        )

        mp_commands.append(cmd)

    return decorator


def register_command(
    trigger: str,
    required_perms: Privileges = Privileges.USER,
    hidden: bool = False,
    aliases: list[str] = [],
    category: str = "undefined",
):
    def decorator(cb: Callable) -> None:
        cmd = Command(
            trigger=cb,
            cmd=trigger,
            aliases=aliases,
            perms=required_perms,
            doc=cb.__doc__,
            hidden=hidden,
            category=category,
        )

        commands.append(cmd)

    return decorator


def ensure_channel(cb: Callable) -> Callable:
    @wraps(cb)
    async def wrapper(ctx: Context, *args, **kwargs):
        if type(ctx.reciever) is Channel:
            return await cb(ctx, *args, **kwargs)

        return "This command can only be performed in a channel."

    return wrapper


def ensure_player(cb: Callable) -> Callable:
    @wraps(cb)
    async def wrapper(ctx: Context, *args, **kwargs):
        if type(ctx.reciever) in (Bot, Player):
            return await cb(ctx, *args, **kwargs)

        return "This command can only be performed in the bots DMs."

    return wrapper


#
# Normal user commands
#


@register_command("help", category="General")
async def help(ctx: Context) -> str | None:
    """The help message"""

    cmds: dict[str, dict[str, str | None]] = {}
    for cmd in commands:
        if cmd.hidden or not cmd.perms & ctx.author.privileges:
            continue

        if cmd.category not in cmds:
            cmds[cmd.category] = {}

        cmds[cmd.category][cmd.cmd] = cmd.doc

    command_list = ""
    for key, value in cmds.items():
        command_list += key + " commands:\n"

        for key, value in value.items():
            command_list += f"!{key} - {value}\n"

        command_list += "\n"

    return "These are the commands supported by our chat bot.\n" + command_list


@register_command("ping", category="General")
async def ping_command(ctx: Context) -> str | None:
    """Ping the server, to see if it responds."""

    return "PONG"


@register_command("roll", category="General")
async def roll(ctx: Context) -> str | None:
    """Roll a dice!"""

    end = 100

    if len(ctx.args) > 1:
        end = int(ctx.args[1])

    return f"{ctx.author.username} rolled {random.randint(0, end)} point(s)"


@dataclass
class PPBuilder:
    accuracy: float = 0.0
    max_combo: int = 0
    count_100: int = 0
    count_50: int = 0
    count_miss: int = 0

    def message(self, perf: Performance, bmap: BMap):
        if not self.accuracy and not (self.count_100 or self.count_50):
            pp_values = []
            for acc in (95, 98, 99, 100):
                perf.set_accuracy(acc)
                pp = perf.calculate(bmap).pp
                pp_values.append(f"{acc}%: {pp:.2f}pp")

            return " | ".join(pp_values)

        perf.set_misses(self.count_miss)

        if self.accuracy:
            if self.max_combo:
                perf.set_combo(self.max_combo)

            perf.set_accuracy(self.accuracy)
            calculator = perf.calculate(bmap)

            return f"{self.accuracy}% {f'{self.max_combo}x' if self.max_combo else ''} {self.count_miss} miss(es): {calculator.pp:.2f}pp"

        if self.max_combo:
            perf.set_combo(self.max_combo)

        perf.set_n100(self.count_100)
        perf.set_n50(self.count_50)
        calculator = perf.calculate(bmap)

        return f"{self.count_100}x100 {self.count_50}x50 {f'{self.max_combo}x' if self.max_combo else ''} {self.count_miss} miss(es): {calculator.pp:.2f}pp"


def pp_message_format(
    rosu_map: BMap,
    map: Beatmap,
    pp_builder: PPBuilder,
    perf: Performance,
    mods: Mods = Mods.NONE,
) -> str | None:
    response = []
    response.append(map.embed)

    if not mods & Mods.NONE:
        response.append(mods.short_name)

    response.append("|")
    perf.set_mods(mods.value)

    response.append(pp_builder.message(perf, rosu_map))

    calculator = perf.calculate(rosu_map)
    attributes = calculator.difficulty

    response.append("| " + map.play_duration(mods))
    response.append(f"★ {attributes.stars:.2f}")
    response.append(f"♫ {rosu_map.bpm:.0f}")

    if rosu_map.mode in (GameMode.Osu, GameMode.Catch):
        response.append(f"AR {attributes.ar:.1f}")

    if rosu_map.mode == GameMode.Osu:
        response.append(f"OD {attributes.od:.1f}")

    if rosu_map.mode in (GameMode.Taiko, GameMode.Mania):
        response.append(f"300: ±{attributes.hit_window:.1f}ms")

    return " ".join(response)


@register_command("pp", category="Tillerino-like")
async def calc_pp_for_map(ctx: Context) -> str | None:
    """Show PP for the previous requested beatmap with requested info (Don't use spaces for multiple mods (eg: !pp +HDHR))"""
    executed_from_match = False
    if "[MULTI]" in ctx.args and (match := ctx.author.match):
        executed_from_match = True
        map = match.map
    else:
        map = ctx.author.last_np

    if not map:
        return "Please /np a map first."

    if not ctx.args:
        return "Usage: !pp [(+)mods | acc(%) | 100s(x100) | 50s(x50) | misses(m) | combo(x)]"

    rosu_map = BMap(path=f".data/beatmaps/{map.file}")

    # if the original map mode is standard, but
    # the user is on another mode, it should convert pp
    mode = map.mode

    if mode == Mode.OSU and mode != ctx.author.play_mode:
        mode = ctx.author.play_mode

    if mode != rosu_map.mode:
        # i hate this stupid fucking library
        if mode == Mode.OSU:
            rosu_mode = GameMode.Osu
        elif mode == Mode.TAIKO:
            rosu_mode = GameMode.Taiko
        elif mode == Mode.CATCH:
            rosu_mode = GameMode.Catch
        else:
            rosu_mode = GameMode.Mania

        rosu_map.convert(rosu_mode)

    # calc is slang for calculator chat
    calc = Performance()

    pp_builder = PPBuilder()
    mods = Mods.NONE

    # maybe regex would be better to use for this case?
    if executed_from_match and ctx.author.match:
        mods = ctx.author.match.mods
    else:
        for arg in ctx.args:
            if arg.startswith("+"):
                mods = Mods.from_str(arg[1:])

            elif arg.endswith("%"):
                if not all(num.isdecimal() for num in arg[:-1].split(".")):
                    return "invalid argument: accuracy has to be a number."

                pp_builder.accuracy = float(arg[:-1])

            elif arg.endswith("x"):
                if not arg[:-1].isdecimal():
                    return "invalid argument: combo has to be a number."

                pp_builder.max_combo = int(arg[:-1])

            elif arg.endswith("x100"):
                if not arg[:-4].isdecimal():
                    return "invalid argument: 100 count has to be a number."

                pp_builder.count_100 = int(arg[:-4])

            elif arg.endswith("x50"):
                if not arg[:-3].isdecimal():
                    return "invalid argument: 50 count has to be a number."

                pp_builder.count_50 = int(arg[:-3])

            elif arg.endswith("m"):
                if not arg[:-1].isdecimal():
                    return "invalid argument: miss count has to be a number."

                pp_builder.count_miss = int(arg[:-1])

    return pp_message_format(rosu_map, map, pp_builder, calc, mods)


@register_command("last", category="Tillerino-like")
async def last_score(ctx: Context) -> str:
    """Show info (and gained PP) about the last submitted score"""
    score = ctx.author.last_score

    if not score:
        return "You haven't set a score, since you started playing."

    map = score.map

    response = (
        map.embed + f"{Mods(score.mods).short_name if score.mods else ''} "
        f"({score.accuracy:.2f}%, {score.rank}) "
        f"{score.max_combo}x/{map.max_combo}x | "
        f"{score.pp:.2f}pp | "
        # TODO: difficulty changing mods changes stars
        f"★ {map.stars:.2f}"
    )

    if not score.status & SubmitStatus.PASSED:
        response += f" [{score.status.name} | {int(score.playtime)/int(map.hit_length)*100:.2f}%]"

    return response


#
# Multiplayer commands
#


def ensure_match(host: bool):
    """Ensures that the command is being executed in a multiplayer match
    also gives the user the option to make the command only executable by the host"""

    def decorator(cb: Callable) -> Callable:
        @wraps(cb)
        async def wrapper(ctx: Context, *args, **kwargs):
            if ctx.author.match and type(ctx.reciever) is Channel:
                if not ctx.reciever.is_multiplayer:
                    return "This command can only be performed in a multiplayer match"

                if (
                    host and ctx.author.match.host != ctx.author.id
                ) and not ctx.author.privileges & Privileges.MODERATOR:
                    return "Only the host can perform this command."

                return await cb(ctx, *args, **kwargs)

            return "This command can only be performed in a multiplayer match"

        return wrapper

    return decorator


@register_mp_command("help")
@ensure_channel
async def multi_help(ctx: Context) -> str | None:
    """Multiplayer help command"""
    return "Not done yet."


@register_mp_command("make")
@ensure_channel
async def make_multi(ctx: Context) -> str | None:
    if ctx.author.match:
        return "Leave the match before making your own."

    if not ctx.args:
        name = ctx.author.username + "'s game"
    else:
        name = " ".join(ctx.args)

    match = Match()
    match.id = len(services.matches)
    match.name = name
    match.host = ctx.author.id

    services.matches.add(match)

    ctx.author.join_match(match)


@register_mp_command("name")
@ensure_match(host=True)
async def change_multi_name(ctx: Context) -> str | None:
    if not ctx.args:
        return "No name has been specified."

    if not (match := ctx.author.match):
        return

    current_name = match.name
    new_name = " ".join(ctx.args)
    match.name = new_name

    match.enqueue_state()
    return f"Changed match name from {current_name} to {new_name}"


@register_mp_command("lock")
@ensure_match(host=True)
async def lock_match(ctx: Context) -> str | None:
    if not (match := ctx.author.match):
        return

    match.is_locked = True

    match.enqueue_state()
    return f"Locked the match"


@register_mp_command("unlock")
@ensure_match(host=True)
async def unlock_match(ctx: Context) -> str | None:
    if not (match := ctx.author.match):
        return

    match.is_locked = True

    match.enqueue_state()
    return f"Unlocked the match"


@register_mp_command("start")
@ensure_match(host=True)
async def start_match(ctx: Context) -> str | None:
    """Start the multiplayer when all players are ready or force start it."""
    if not (match := ctx.author.match):
        return

    if ctx.args:
        if ctx.args[0] == "force":
            for slot in match.slots:
                if slot.player is not None and slot.status.is_occupied:
                    if slot.status != SlotStatus.NOMAP:
                        slot.status = SlotStatus.PLAYING
                        slot.player.enqueue(writer.match_start(match))

            match.in_progress = True

            match.enqueue_state(lobby=True)
            return "Starting match... Good luck!"

    if not all(
        slot.status == SlotStatus.READY
        for slot in match.slots
        if slot.status.is_occupied
    ):
        return 'All players aren\'t ready, do "!mp start force" to force ready all players and start the map.'

    for slot in match.slots:
        if slot.status.is_occupied:
            slot.status = SlotStatus.PLAYING

    match.in_progress = True

    match.enqueue(writer.match_start(match))
    match.enqueue_state()
    return "Starting match... Good luck!"


@register_mp_command("abort", aliases=["ab"])
@ensure_match(host=True)
async def abort_match(ctx: Context) -> str | None:
    if not (match := ctx.author.match):
        return

    for slot in match.slots:
        if slot.status == SlotStatus.PLAYING and slot.player is not None:
            slot.player.enqueue(writer.write(ServerPackets.MATCH_ABORT))
            slot.status = SlotStatus.NOTREADY

            slot.skipped = False
            slot.loaded = False

    match.in_progress = False

    match.enqueue_state(lobby=True)
    return "Aborted match."


@register_mp_command("win", aliases=["wc"])
@ensure_match(host=True)
async def win_condition(ctx: Context) -> str | None:
    """Change win condition in a multiplayer match."""
    if not (match := ctx.author.match):
        return

    if not ctx.args:
        return "Wrong usage. !mp win <score/acc/combo/sv2/pp>"

    if ctx.args[0] in ("score", "acc", "sv2", "combo"):
        old_scoring = copy.copy(match.scoring_type)
        match.scoring_type = ScoringType.from_name(ctx.args[0])

        match.enqueue_state()
        return f"Changed win condition from {old_scoring.name.lower()} to {match.scoring_type.name.lower()}"
    elif ctx.args[0] == "pp":
        match.scoring_type = ScoringType.SCORE  # force it to be score
        match.pp_win_condition = True

        match.enqueue_state()
        return (
            "Changed win condition to pp. THIS IS IN BETA AND CAN BE REMOVED ANY TIME."
        )

    return "Not a valid win condition"


@register_mp_command("move")
@ensure_match(host=True)
async def move_slot(ctx: Context) -> str | None:
    if not (match := ctx.author.match):
        return

    if len(ctx.args) < 2:
        return "Wrong usage: !mp move <player> <to_slot>"

    slot_id = int(ctx.args[1]) - 1

    if not (player := services.players.get(ctx.args[0])):
        return

    if not (target := match.find_user(player)):
        return "Slot is not occupied."

    if not (move_to := match.find_slot(slot_id)):
        return "out of range."

    if not target.player or not move_to.player:
        return

    if move_to.status.is_occupied:
        return "That slot is already occupied."

    move_to.copy_from(target)
    target.reset()

    match.enqueue_state(lobby=True)

    return f"Moved {move_to.player.username} to slot {slot_id + 1}"


@register_mp_command("size")
@ensure_match(host=True)
async def change_size(ctx: Context) -> str | None:
    if not (match := ctx.author.match):
        return

    if not ctx.args:
        return "Wrong usage: !mp size <amount of available slots>"

    size = int(ctx.args[0])

    if size > 16:
        return "You can't choose a size bigger than 16."

    for slot_id in range(0, size):
        if not (slot := match.find_slot(slot_id)):
            return

        if not slot.status.is_occupied:
            slot.status = SlotStatus.LOCKED

    return f"Changed size to {ctx.args[0]}"


@register_mp_command("get")
@ensure_match(host=False)
async def get_beatmap(ctx: Context) -> str | None:
    if not (match := ctx.author.match):
        return

    # TODO: rewrite

    mirrors = {
        "chimu": settings.MIRROR_CHIMU,
        "nerinyan": settings.MIRROR_NERINYAN,
        "katsu": settings.MIRROR_KATSU,
    }

    if not ctx.args:
        return f"Wrong usage: !mp get <{'|'.join(mirrors.keys())}>"

    if not match.map:
        return "The host has probably choosen a map that needs to be updated! Tell them to do so!"

    if ctx.args[0] not in mirrors:
        return "Mirror doesn't exist in our database"

    url = mirrors[ctx.args[0]]

    match ctx.args[0]:
        case "chimu":
            url += f"download/{match.map.set_id}"
        case "katsu":
            url += f"d/{match.map.set_id}"
        case "nerinyan":
            url += f"d/{match.map.set_id}"

    return f"[{url} Download beatmap from {ctx.args[0]}]"


@register_mp_command("invite")
@ensure_match(host=False)
async def invite_people(ctx: Context) -> str | None:
    if not (match := ctx.author.match):
        return

    if not ctx.args:
        return "Wrong usage: !mp invite <username>"

    if not (target := services.players.get(ctx.args[0])):
        return "The user is not online."

    if target == ctx.author:
        return "You can't invite yourself."

    ctx.author.send(
        "Come join my multiplayer match: "
        f"[osump://{match.id}/{match.password.replace(' ', '_')} {match.name}]",
        target,
    )

    return f"Invited {target.username}"


@register_mp_command("host")
@ensure_match(host=True)
async def change_host(ctx: Context) -> str | None:
    if not (match := ctx.author.match):
        return

    if not ctx.args:
        return "Wrong usage: !mp invite <username>"

    if not (target := services.players.get(ctx.args[0])):
        return "The user either is not online or doesn't exist."

    target = match.find_user(target)

    if not target:
        return "The user isn't in your match."

    match.transfer_host(target)


#
# Staff commands
#


@register_command("announce", category="Staff", required_perms=Privileges.MODERATOR)
async def announce(ctx: Context) -> str | None:
    """Spread the message to the whole world."""
    if len(ctx.args) < 2:
        return

    msg = " ".join(ctx.args[1:])

    if ctx.args[0] == "all":
        services.players.enqueue(writer.notification(msg))
    else:
        if not (target := services.players.get(ctx.args[0])):
            return "Player is not online."

        target.shout(msg)

    return "ok"


@register_command("kick", category="Staff", required_perms=Privileges.MODERATOR)
async def kick_user(ctx: Context) -> str | None:
    """Kick all players or just one player from the server."""

    if not ctx.args:
        return "Usage: !kick <username>"

    if ctx.args[0].lower() == "all":
        for player in services.players:
            if (player == ctx.author) or player.is_bot:
                continue

            await player.logout()

        return "Kicked every. single. user online."

    if not (target := await services.players.get_offline(" ".join(ctx.args))):
        return "Player isn't online or couldn't be found in the database"

    if target.is_bot:
        return "You can't kick me from the server!"

    await target.logout()
    target.shout("You've been kicked!")

    return f"Successfully kicked {target.username}"


@register_command("restrict", category="Staff", required_perms=Privileges.ADMIN)
@ensure_channel
async def restrict_user(ctx: Context) -> str | None:
    """Restrict users from the server."""
    if len(ctx.args) < 1:
        return "Usage: !restrict <username>"

    if not (target := await services.players.get_offline(" ".join(ctx.args))):
        return "Player isn't online or couldn't be found in the database"

    if target.is_restricted:
        return "Player is already restricted? Did you mean to unrestrict them?"

    services.loop.create_task(
        services.database.execute(
            "UPDATE users SET privileges = privileges - 4 WHERE id = :user_id",
            {"user_id": target.id},
        )
    )

    target.privileges -= Privileges.VERIFIED
    target.shout("An admin has set your account in restricted mode!")

    await ctx.author.log(f"restricted {target.username}", type=LoggingType.RESTRICTIONS)

    return f"Successfully restricted {target.username}"


@register_command("unrestrict", category="Staff", required_perms=Privileges.ADMIN)
@ensure_channel
async def unrestrict_user(ctx: Context) -> str | None:
    """Unrestrict users from the server."""
    if len(ctx.args) < 1:
        return "Usage: !unrestrict <username>"

    if not (target := await services.players.get_offline(" ".join(ctx.args))):
        return "Player couldn't be found in the database"

    if not target.is_restricted:
        return "Player isn't even restricted?"

    await services.database.execute(
        "UPDATE users SET privileges = privileges + 4 WHERE id = :user_id",
        {"user_id": target.id},
    )

    target.privileges |= Privileges.VERIFIED

    if target.token:  # if user is online
        target.shout("An admin has unrestricted your account!")

    await ctx.author.log(
        f"unrestricted {target.username}", type=LoggingType.RESTRICTIONS
    )

    return f"Successfully unrestricted {target.username}"


@register_command("bot", category="Staff", required_perms=Privileges.ADMIN)
@ensure_player
async def bot_commands(ctx: Context) -> str | None:
    """Handle the bot ingame."""
    if type(ctx.reciever) != Bot:
        return

    if not ctx.args:
        return f"{services.bot.username.lower()}."

    if ctx.args[0] == "reconnect":
        if services.players.get(1):
            return f"{services.bot.username} is already connected."

        await Bot.initialize()

        return f"Successfully connected {services.bot.username}."


@register_command("approve", category="Staff", required_perms=Privileges.BAT)
async def approve_map(ctx: Context) -> str | None:
    """Change the ranked status of beatmaps."""
    if not (map := ctx.author.last_np):
        return "Please /np a map first."

    return f"[https://admin.rina.place/rank/set/{map.set_id} Beatmap ranking has been moved to the admin panel.]"


@register_command(
    "system", aliases=["sys"], category="Admin", required_perms=Privileges.ADMIN
)
@ensure_channel
async def system(ctx: Context) -> str | None:
    """Control the server system from ingame!"""
    if not ctx.args:
        return f"Wrong usage: !{ctx.cmd} [restart | shutdown | reload | maintenance]"

    match ctx.args[0].lower():
        case "restart":
            # TODO: add timer
            ctx.reciever.send("Restarting server...", services.bot)
            os.execl(sys.executable, sys.executable, *sys.argv)

        case "shutdown":
            ctx.reciever.send("Shutting down server...", services.bot)
            os.kill(os.getpid(), signal.SIGTERM)

        case "reload":
            await services.osu_settings.initialize_from_db()

            return "Succesfully reloaded all osu settings"

        case "maintenance":
            # TODO: this
            return "beep boop"

        case _:
            return "Argument is invalid."


@register_command("forceerror", hidden=True, required_perms=Privileges.DEVELOPER)
async def force_error(ctx: Context) -> str | None:
    raise Exception("forced error...")


async def handle_commands(
    message: str, sender: "Player", reciever: Union["Channel", "Player"]
) -> str | None:
    if message[:3] == "!mp":
        message = message[4:]
        commands_set = mp_commands
    else:
        message = message[1:]
        commands_set = commands

    ctx = Context(
        author=sender,
        reciever=reciever,
        cmd=message.split(" ")[0].lower(),
        args=message.split(" ")[1:],
    )

    for command in commands_set:
        if ctx.cmd != command.cmd or not command.perms & ctx.author.privileges:
            if ctx.cmd not in command.aliases:
                continue
        try:
            response = await command.trigger(ctx)
        except Exception as exp:
            services.logger.error(traceback.format_exc())

            response = f"unhandled error: {exp} (contact Simon about this)"

            if not (ach := services.get_achievement_by_id(190)):
                return

            user_achievement = UserAchievement(
                **ach.__dict__, gamemode=Gamemode.UNKNOWN, mode=Mode.NONE
            )

            if user_achievement not in sender.achievements:
                await services.database.execute(
                    "INSERT INTO users_achievements "
                    "(user_id, achievement_id, mode, gamemode) VALUES (:user_id, :ach_id, -1, -1)",
                    {"user_id": sender.id, "ach_id": 190},
                )

                sender.achievements.append(user_achievement)

                sender.shout("You've unlocked \"IT'S A FEATURE!\" achievement!")

        return response

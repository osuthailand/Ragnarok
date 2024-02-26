import math
import copy
import os
import signal
import sys
import uuid
import time
import random
import asyncio
from events import osu
from objects.achievement import UserAchievement
from objects.beatmap import Beatmap
from objects.match import Match
from objects.score import SubmitStatus

from typing import Union
from packets import writer
from typing import Callable
from objects import services
from dataclasses import dataclass
from rina_pp_pyb import Beatmap as BMap, Calculator

from objects.bot import Bot
from constants.mods import Mods
from constants.playmode import Gamemode, Mode
from constants.beatmap import Approved
from constants.player import Privileges
from constants.packets import BanchoPackets
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

    # there is probably a better solution to this
    # but this is just what i quickly came up with
    async def await_response(self) -> str | None:
        services.await_response[self.author.token] = ""

        # they will have 60 seconds to respond.
        for i in range(0, 60):
            if services.await_response[self.author.token]:
                msg = services.await_response[self.author.token]
                services.await_response.pop(self.author.token)

                if msg[0] == "!":
                    pass

                return msg

            await asyncio.sleep(1)
        else:
            return ""


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


def rmp_command(
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

    cmds: dict[str, dict[str, str]] = {}
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

    x = 100

    if len(ctx.args) > 1:
        x = int(ctx.args[1])

    return f"{ctx.author.username} rolled {random.randint(0, x)} point(s)"


@register_command(
    "verify", category="Player", hidden=True, required_perms=Privileges.PENDING
)
@ensure_player
async def verify_with_key(ctx: Context) -> str | None:
    """Verify your account with our key system!"""
    if not ctx.reciever.bot:
        return

    if not ctx.args:
        return "Usage: !verify <your beta key>"

    key = ctx.args[0]

    if not (
        key_info := await services.sql.fetch(
            "SELECT id, beta_key, made FROM beta_keys WHERE beta_key = %s", (
                key)
        )
    ):
        return "Invalid key"

    asyncio.create_task(
        services.sql.execute(
            "UPDATE users SET privileges = %s WHERE id = %s",
            (Privileges.USER.value + Privileges.VERIFIED.value, ctx.author.id),
        )
    )

    asyncio.create_task(
        services.sql.execute(
            "DELETE FROM beta_keys WHERE id = %s", key_info["id"])
    )

    ctx.author.privileges = Privileges.USER + Privileges.VERIFIED
    
    ctx.author.shout(
        "Welcome to Ragnarok. You've successfully verified your account and gained beta access! "
        "If you see any bugs or anything unusal, please report it to one of the developers, through "
        "Github issues or Discord."
    )
    ctx.author.shout("Please login again to prevent any corruption to your user data!")

    services.logger.info(
        f"{ctx.author.username} successfully verified their account with a key")

    return "Successfully verified your account."


@dataclass
class PPBuilder:
    accuracy: float = 0.0
    combo: int = 0
    x100: int = 0
    x50: int = 0
    misses: int = 0

    def message(self, calculator: Calculator, bmap: BMap):
        if not self.accuracy and not (self.x100 or self.x50):
            pp_values = []
            for acc in (95, 98, 99, 100):
                calculator.set_acc(acc)
                pp = calculator.performance(bmap).pp
                pp_values.append(f"{acc}%: {pp:.2f}pp")

            return " | ".join(pp_values)

        calculator.set_n_misses(self.misses)

        if self.accuracy:
            if self.combo:
                calculator.set_combo(self.combo)

            calculator.set_acc(self.accuracy)
            performance = calculator.performance(bmap)

            return f"{self.accuracy}% {f'{self.combo}x' if self.combo else ''} {self.misses} miss(es): {performance.pp:.2f}pp"

        if self.combo:
            calculator.set_combo(self.combo)

        calculator.set_n100(self.x100)
        calculator.set_n50(self.x50)
        performance = calculator.performance(bmap)

        return f"{self.x100}x100 {self.x50}x50 {f'{self.combo}x' if self.combo else ''} {self.misses} miss(es): {performance.pp:.2f}pp"


def pp_message_format(
    bmap: BMap,
    map: Beatmap,
    pp_builder: PPBuilder,
    calculator: Calculator,
    mods: Mods = Mods.NONE,
) -> str | None:
    response = []
    response.append(map.embed)

    if not mods & Mods.NONE:
        response.append(mods.short_name)

    response.append("|")
    calculator.set_mods(mods.value)

    response.append(pp_builder.message(calculator, bmap))

    map_attributes = calculator.map_attributes(bmap)
    difficulty_attributes = calculator.difficulty(bmap)

    response.append("| " + map.length_in_minutes_seconds(mods))
    response.append(f"★ {difficulty_attributes.stars:.2f}")
    response.append(f"♫ {map_attributes.bpm:.0f}")
    response.append(f"AR {map_attributes.ar:.1f}")
    response.append(f"OD {map_attributes.od:.1f}")

    return " ".join(response)


@register_command("pp", category="Tillerino-like")
async def calc_pp_for_map(ctx: Context) -> str | None:
    """Show PP for the previous requested beatmap with requested info (Don't use spaces for multiple mods (eg: !pp +HDHR))"""
    executed_from_match = False
    if "[MULTI]" in ctx.args and ctx.author.match:
        executed_from_match = True
        _map = ctx.author.match.map
    else:
        _map = ctx.author.last_np

    if not _map:
        return "Please /np a map first."

    if not ctx.args:
        return "Usage: !pp [(+)mods | acc(%) | 100s(x100) | 50s(x50) | misses(m) | combo(x)]"

    bmap = BMap(path=f".data/beatmaps/{_map.file}")

    # if the original map mode is standard, but
    # the user is on another mode, it should convert pp
    mode = _map.mode

    if mode == Mode.OSU and mode != ctx.author.play_mode:
        mode = ctx.author.play_mode

    calc = Calculator(mode=mode)

    pp_builder = PPBuilder()
    mods = Mods.NONE

    # maybe regex would be better to use for this case?
    if executed_from_match:
        mods = ctx.author.match.mods
    else:
        for arg in ctx.args:
            if arg.startswith("+"):
                mods = Mods.from_str(arg[1:])

            elif arg.endswith("%"):
                pp_builder.accuracy = float(arg[:-1])

            elif arg.endswith("x"):
                pp_builder.combo = int(arg[:-1])

            elif arg.endswith("x100"):
                pp_builder.x100 = int(arg[:-4])

            elif arg.endswith("x50"):
                pp_builder.x50 = int(arg[:-3])

            elif arg.endswith("m"):
                pp_builder.misses = int(arg[:-1])

    return pp_message_format(bmap, _map, pp_builder, calc, mods)


@register_command("last", category="Tillerino-like")
async def last_score(ctx: Context) -> str:
    """Show info (and gained PP) about the last submitted score"""
    score = ctx.author.last_score

    if not score:
        return "You haven't set a score, since you started playing."

    bmap = score.map

    initial_response = (
        bmap.embed + f"{Mods(score.mods).short_name if score.mods else ''} "
        f"({score.accuracy:.2f}%, {score.rank}) "
        f"{score.max_combo}x/{bmap.max_combo}x | "
        # TODO: difficulty changing mods changes stars
        f"{score.pp:.2f}pp | ★ {bmap.stars:.2f} "
    )

    if not score.status & SubmitStatus.PASSED:
        initial_response += f"[{score.status.name} | {
            int(score.playtime)/int(bmap.hit_length)*100:.2f}%]"

    return initial_response


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
                if not ctx.reciever.is_multi:
                    return "This command can only be performed in a multiplayer match"

                if (
                    host and ctx.author.match.host != ctx.author.id
                ) and not ctx.author.privileges & Privileges.MODERATOR:
                    return "Only the host can perform this command."

                return await cb(ctx, *args, **kwargs)

            return "This command can only be performed in a multiplayer match"

        return wrapper

    return decorator


@rmp_command("help")
@ensure_channel
async def multi_help(ctx: Context) -> str | None:
    """Multiplayer help command"""
    return "Not done yet."


@rmp_command("make")
@ensure_channel
async def make_multi(ctx: Context) -> str | None:
    if ctx.author.match:
        return "Leave the match before making your own."

    if not ctx.args:
        name = ctx.author.username + "'s game"
    else:
        name = " ".join(ctx.args)

    m = Match()
    m.match_id = len(services.matches)
    m.match_name = name
    m.host = ctx.author.id

    services.matches.add(m)

    ctx.author.join_match(m)


@rmp_command("name")
@ensure_match(host=True)
async def change_multi_name(ctx: Context) -> str | None:
    if not ctx.args:
        return "No name has been specified."

    m = ctx.author.match
    current_name = m.match_name
    new_name = " ".join(ctx.args)
    m.match_name = new_name

    m.enqueue_state()
    return f"Changed match name from {current_name} to {new_name}"


@rmp_command("lock")
@ensure_match(host=True)
async def lock_match(ctx: Context) -> str | None:
    m = ctx.author.match
    m.locked = True

    m.enqueue_state()
    return f"Locked the match"


@rmp_command("unlock")
@ensure_match(host=True)
async def unlock_match(ctx: Context) -> str | None:
    m = ctx.author.match
    m.locked = True

    m.enqueue_state()
    return f"Unlocked the match"


@rmp_command("start")
@ensure_match(host=True)
async def start_match(ctx: Context) -> str | None:
    """Start the multiplayer when all players are ready or force start it."""
    m = ctx.author.match

    if ctx.args:
        if ctx.args[0] == "force":
            for slot in m.slots:
                if slot.status & SlotStatus.OCCUPIED:
                    if slot.status != SlotStatus.NOMAP:
                        slot.status = SlotStatus.PLAYING
                        slot.player.enqueue(writer.match_start(m))

            m.in_progress = True

            m.enqueue_state(lobby=True)
            return "Starting match... Good luck!"

    if not all(
        slot.status == SlotStatus.READY
        for slot in m.slots
        if slot.status & SlotStatus.OCCUPIED
    ):
        ctx.reciever.send(
            message="All players aren't ready, would you like to force start? (y/n)",
            sender=services.bot,
        )
        response = await ctx.await_response()
        if response == "n":
            return

    for slot in m.slots:
        if slot.status & SlotStatus.OCCUPIED:
            slot.status = SlotStatus.PLAYING

    m.in_progress = True

    m.enqueue(writer.match_start(m))
    m.enqueue_state()
    return "Starting match... Good luck!"


@rmp_command("abort", aliases=["ab"])
@ensure_match(host=True)
async def abort_match(ctx: Context) -> str | None:
    m = ctx.author.match

    for s in m.slots:
        if s.status == SlotStatus.PLAYING:
            s.player.enqueue(writer.write(BanchoPackets.CHO_MATCH_ABORT))
            s.status = SlotStatus.NOTREADY

            s.skipped = False
            s.loaded = False

    m.in_progress = False

    m.enqueue_state(lobby=True)
    return "Aborted match."


@rmp_command("win", aliases=["wc"])
@ensure_match(host=True)
async def win_condition(ctx: Context) -> str | None:
    """Change win condition in a multiplayer match."""
    m = ctx.author.match

    if not ctx.args:
        return f"Wrong usage. !mp {ctx.cmd} <score/acc/combo/sv2/pp>"

    if ctx.args[0] in ("score", "acc", "sv2", "combo"):
        old_scoring = copy.copy(m.scoring_type)
        m.scoring_type = ScoringType.find_value(ctx.args[0])

        m.enqueue_state()
        return f"Changed win condition from {old_scoring.name.lower()} to {m.scoring_type.name.lower()}"
    elif ctx.args[0] == "pp":
        m.scoring_type = ScoringType.SCORE  # force it to be score
        m.pp_win_condition = True

        m.enqueue_state()
        return (
            "Changed win condition to pp. THIS IS IN BETA AND CAN BE REMOVED ANY TIME."
        )

    return "Not a valid win condition"


@rmp_command("move")
@ensure_match(host=True)
async def move_slot(ctx: Context) -> str | None:
    m = ctx.author.match

    if len(ctx.args) < 2:
        return "Wrong usage: !mp move <player> <to_slot>"

    slot_id = int(ctx.args[1]) - 1

    player = services.players.get(ctx.args[0])

    if not (target := m.find_user(player)):
        return "Slot is not occupied."

    to = m.find_slot(slot_id)
    assert to is not None

    if to.status & SlotStatus.OCCUPIED:
        return "That slot is already occupied."

    to.copy_from(target)
    target.reset()

    m.enqueue_state(lobby=True)

    return f"Moved {to.player.username} to slot {slot_id + 1}"


@rmp_command("size")
@ensure_match(host=True)
async def change_size(ctx: Context) -> str | None:
    m = ctx.author.match

    if not ctx.args:
        return "Wrong usage: !mp size <amount of available slots>"

    size = int(ctx.args[0])

    if size > 16:
        return "You can't choose a size bigger than 16."

    for slot_id in range(0, size):
        slot = m.find_slot(slot_id)

        if not slot.status & SlotStatus.OCCUPIED:
            slot.status = SlotStatus.LOCKED

    return f"Changed size to {ctx.args[0]}"


@rmp_command("get")
@ensure_match(host=False)
async def get_beatmap(ctx: Context) -> str | None:
    m = ctx.author.match
    mirrors = services.config.api.mirrors

    if not ctx.args:
        return f"Wrong usage: !mp get <{'|'.join(mirrors.keys())}>"

    if not m.map:
        return "The host has probably choosen a map that needs to be updated! Tell them to do so!"

    if ctx.args[0] not in mirrors:
        return "Mirror doesn't exist in our database"

    url = mirrors[ctx.args[0]]

    match ctx.args[0]:
        case "chimu":
            url += f"download/{m.map.set_id}"
        case "katsu":
            url += f"d/{m.map.set_id}"
        case "nerinyan":
            url += f"d/{m.map.set_id}"

    return f"[{url} Download beatmap from {ctx.args[0]}]"


@rmp_command("invite")
@ensure_match(host=False)
async def invite_people(ctx: Context) -> str | None:
    m = ctx.author.match

    if not ctx.args:
        ctx.reciever.send(
            message="Who do you want to invite?", sender=services.bot
        )
        response = await ctx.await_response()

        if not (target := services.players.get(response)):
            return "The user is not online."
    else:
        if not (target := services.players.get(ctx.args[0])):
            return "The user is not online."

    if target is ctx.author:
        return "You can't invite yourself."

    ctx.author.send_message(
        f"Come join my multiplayer match: [osump://{m.match_id}/{
            m.match_pass.replace(' ', '_')} {m.match_name}]",
        reciever=target,
    )

    return f"Invited {target.username}"


@rmp_command("host")
@ensure_match(host=True)
async def change_host(ctx: Context) -> str | None:
    m = ctx.author.match

    if not ctx.args:
        ctx.reciever.send(
            message="Who do you want to invite?", sender=services.bot
        )

        response = await ctx.await_response()

        if not (target := services.players.get(response)):
            return "The user either is not online or doesn't exist."
    else:
        if not (target := services.players.get(ctx.args[0])):
            return "The user either is not online or doesn't exist."

    target_slot = m.find_user(target)

    if not target_slot:
        return "The user isn't in your match."

    m.transfer_host(target_slot)


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
        for p in services.players:
            if (p == ctx.author) or p.bot:
                continue

            p.logout()

        return "Kicked every. single. user online."

    if not (t := await services.players.get_offline(" ".join(ctx.args))):
        return "Player isn't online or couldn't be found in the database"

    if t.bot:
        return "You can't kick me from the server!"

    t.logout()
    t.enqueue(writer.notification("You've been kicked!"))

    return f"Successfully kicked {t.username}"


@register_command("restrict", category="Staff", required_perms=Privileges.ADMIN)
@ensure_channel
async def restrict_user(ctx: Context) -> str | None:
    """Restrict users from the server."""
    if ctx.reciever.name != "#staff":
        return "You can't do that here."

    if len(ctx.args) < 1:
        return "Usage: !restrict <username>"

    if not (target := await services.players.get_offline(" ".join(ctx.args))):
        return "Player isn't online or couldn't be found in the database"

    if target.is_restricted:
        return "Player is already restricted? Did you mean to unrestrict them?"

    asyncio.create_task(
        services.sql.execute(
            "UPDATE users SET privileges = privileges - 4 WHERE id = %s", (
                target.id)
        )
    )

    target.privileges -= Privileges.VERIFIED
    target.shout("An admin has set your account in restricted mode!")

    await ctx.author.log(f"restricted {target.username}", type = LoggingType.RESTRICTIONS)

    return f"Successfully restricted {target.username}"


@register_command("unrestrict", category="Staff", required_perms=Privileges.ADMIN)
@ensure_channel
async def unrestrict_user(ctx: Context) -> str | None:
    """Unrestrict users from the server."""
    if ctx.reciever.name != "#staff":
        return "You can't do that here."

    if len(ctx.args) < 1:
        return "Usage: !unrestrict <username>"

    if not (target := await services.players.get_offline(" ".join(ctx.args))):
        return "Player couldn't be found in the database"

    if not target.is_restricted:
        return "Player isn't even restricted?"

    await services.sql.execute(
        "UPDATE users SET privileges = privileges + 4 WHERE id = %s", (target.id)
    )

    target.privileges |= Privileges.VERIFIED

    if target.token:  # if user is online
        target.shout("An admin has unrestricted your account!")

    await ctx.author.log(f"unrestricted {target.username}", type = LoggingType.RESTRICTIONS)

    return f"Successfully unrestricted {target.username}"


@register_command("bot", category="Staff", required_perms=Privileges.ADMIN)
@ensure_player
async def bot_commands(ctx: Context) -> str | None:
    """Handle the bot ingame."""
    if not ctx.reciever.bot:
        return

    if not ctx.args:
        return f"{services.bot.username.lower()}."

    if ctx.args[0] == "reconnect":
        if services.players.get(1):
            return f"{services.bot.username} is already connected."

        await Bot.init()

        return f"Successfully connected {services.bot.username}."


@register_command("approve", category="Staff", required_perms=Privileges.BAT)
async def approve_map(ctx: Context) -> str | None:
    """Change the ranked status of beatmaps."""
    # maybe remove this, and add it to admin panel?

    if not ctx.author.last_np:
        return "Please /np a map first."

    bmap = ctx.author.last_np

    if len(ctx.args) != 2:
        return "Usage: !approve <set/map> <rank/love/unrank>"

    if not ctx.args[0] in ("map", "set"):
        return "Invalid first argument (map or set)"

    if not ctx.args[1] in ("rank", "love", "unrank"):
        return "Invalid approved status (rank, love or unrank)"

    ranked_status = {
        "rank": Approved.RANKED,
        "love": Approved.LOVED,
        "unrank": Approved.PENDING,
    }[ctx.args[1]]

    if bmap.approved == ranked_status.value:
        return f"Map is already {ranked_status.name}"

    condition = {"map": "map_id", "set": "set_id"}[ctx.args[0]]

    await services.sql.execute(
        "UPDATE beatmaps SET approved = %s " f"WHERE {condition} = %s",
        (ranked_status.value, bmap.map_id if condition == "map_id" else bmap.set_id),
    )

    if condition == "set_id":
        title = f"{bmap.artist} - {bmap.title}"
    else:
        title = bmap.full_title

    resp = f"Successfully changed {title}'s status, from {
        Approved(bmap.approved).name} to {ranked_status.name}"

    await ctx.author.log(
        f"changed {title}'s status from {Approved(bmap.approved).name} to {
            ranked_status.name}"
    )

    bmap.approved = ranked_status

    if condition == "set_id":
        set = services.beatmaps.get_maps_from_set_id(bmap.set_id)

        for hash in set:
            services.beatmaps[hash].approved = ranked_status
    else:
        # do i even need this check?
        if ctx.author.last_np.map_md5 in services.beatmaps:
            services.beatmaps[ctx.author.last_np.map_md5].approved = ranked_status

    return resp


@register_command("recalc", category="Admin", required_perms=Privileges.ADMIN)
async def recalc_scores(ctx: Context) -> str | None:
    """Recalculate all the scores on either relax or vanilla."""

    if len(ctx.args) < 2:
        return "Usage: !recalc <relax/vanilla> <std/taiko/catch/mania>"

    gamemode = Gamemode.from_str(ctx.args[0].lower())
    mode = Mode.from_str(ctx.args[1].lower())

    if gamemode == Gamemode.UNKNOWN or mode == Mode.NONE:
        return "Usage: !recalc <relax/vanilla> <std/taiko/catch/mania>"

    ctx.reciever.send(
        message=f"Fetching EVERY SCORE on the server for {
            ctx.args[1].lower()} {
            ctx.args[0].lower()}...",
        sender=services.bot,
    )

    async for score in services.sql.iterall(
        "SELECT s.id, s.mods, s.count_300, s.count_100, s.count_50, "
        "s.count_geki, s.count_katu, s.count_miss, s.max_combo, "
        "s.accuracy, b.map_id, s.mode, s.pp, b.title, "
        "b.version, b.artist FROM scores s "
        "INNER JOIN beatmaps b ON b.map_md5 = s.map_md5 "
        "WHERE s.gamemode = %s AND s.mode = %s AND s.status = 3",  # 3: best
        (gamemode, mode.value),
    ):
        try:
            bmap = BMap(path=f".data/beatmaps/{score['map_id']}.osu")
        except:
            ctx.reciever.send(message="No beatmap with that id found on server... Getting from osu api...", sender=services.bot)
            await osu.save_beatmap_file(score["map_id"])
            await asyncio.sleep(2)
            ctx.reciever.send(message="Waiting 2 seconds before continuing to prevent rate limiting.", sender=services.bot)
            try:
                bmap = BMap(path=f".data/beatmaps/{score['map_id']}.osu")
            except:
                ctx.reciever.send(message="welp couldn't find beatmap lol", sender=services.bot)
                continue

        calc = Calculator(
            mode=score["mode"],
            n300=score["count_300"],
            n100=score["count_100"],
            n50=score["count_50"],
            n_misses=score["count_miss"],
            n_geki=score["count_geki"],
            n_katu=score["count_katu"],
            combo=score["max_combo"],
            acc=score["accuracy"],
            mods=score["mods"],
        )

        pp = calc.performance(bmap).pp

        if math.isnan(pp):
            ctx.reciever.send(
                message=f"Failed to recalculate pp for score {score['id']} on map {
                    score['artist']} - {score['title']} [{score['version']}]",
                sender=services.bot,
            )
            pp = 0

        await services.sql.execute(
            "UPDATE scores SET pp = %s WHERE id = %s", (pp, score["id"])
        )

        ctx.reciever.send(
            message=f"Finished recalculating score {
                score['id']} (before: {round(score['pp'], 4)}, after: {round(pp, 4)})",
            sender=services.bot,
        )

    await ctx.author.log(f"recalculated all scores for {ctx.args[0]}", type = LoggingType.RECALCULATIONS)

    return f"Finished recalculating all scores for {ctx.args[0]}"


@register_command("key", category="Admin", required_perms=Privileges.ADMIN)
async def beta_keys(ctx: Context) -> str | None:
    """Create or delete keys."""

    if len(ctx.args) < 1:
        return "Usage: !key <create/delete> <name if create (OPTIONAL) / id if delete>"

    if ctx.args[0] == "create":
        if len(ctx.args) != 2:
            key = uuid.uuid4().hex
            id = await services.sql.execute(
                "INSERT INTO beta_keys VALUES (NULL, %s, %s)",
                (key, time.time() + 432000),  # 5 days
            )
        else:
            key = ctx.args[1]
            id = await services.sql.execute(
                "INSERT INTO beta_keys VALUES (NULL, %s, %s)",
                (key, time.time() + 432000),  # 5 days
            )

        return f"Created key with the name {key} (id: {id})"

    elif ctx.args[0] == "delete":
        if len(ctx.args) != 2:
            return "Usage: !key delete <key id>"

        key_id = ctx.args[1]

        if not await services.sql.fetch(
            "SELECT 1 FROM beta_keys WHERE id = %s", (key_id)
        ):
            return "Key doesn't exist"

        await services.sql.execute(
                "DELETE FROM beta_keys WHERE id = %s", (key_id)
        )

        return f"Deleted key {key_id}"

    return "Usage: !key <create/delete> <name if create (OPTIONAL) / id if delete>"


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
            ctx.reciever.send(message="Restarting server...", sender=services.bot)
            os.execl(sys.executable, sys.executable, *sys.argv)

        case "shutdown":
            ctx.reciever.send(
                message="Shutting down server...", sender=services.bot
            )
            os.kill(os.getpid(), signal.SIGTERM)

        case "reload":
            await services.osu_settings.initialize_from_db()

            return "Succesfully reloaded all osu settings"

        case "maintenance":
            # TODO: this
            return "beep boop"

        case _:
            return "Argument is invalid."


# group commands
# @register_command("group", hidden=True, required_perms=Privileges.DEV)
# async def creategroup(ctx: Context) -> str | None:
#     if len(ctx.args) != 1:
#         return "Usage: !group <name>"

#     if services.channels.get(name := ctx.args[0]):
#         return "Group name already created (fix)"

#     await Group.create(ctx.author, name)

#     return f"Created group `{name}`"

@register_command("forceerror", hidden=True, required_perms=Privileges.DEV)
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
        except Exception as e:
            response = f"unhandled error: {e} (contact Simon about this)"

            assert (ach := services.get_achievement_by_id(190)) is not None
            user_achievement = UserAchievement(
                **ach.__dict__,
                gamemode=Gamemode.UNKNOWN,
                mode=Mode.NONE
            )

            if user_achievement not in sender.achievements:
                await services.sql.execute(
                    "INSERT INTO users_achievements "
                    "(user_id, achievement_id, mode, gamemode) VALUES (%s, %s, -1, -1)",
                    (sender.id, 190),
                )

                sender.achievements.append(user_achievement)

                sender.shout("You've unlocked \"IT'S A FEATURE!\" achievement!")

        return response

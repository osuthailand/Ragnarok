from datetime import datetime
from enum import IntEnum, unique
import os
import time
import copy
import bcrypt
import struct
import asyncio
import math
import timeago

from packets import writer
from typing import Callable
from objects import services
from constants import commands as cmd
from rina_pp_pyb import GameMode, Performance, Beatmap as BMap

from constants.match import SlotStatus, SlotTeams
from constants.mods import Mods
from objects.player import LoggingType, Player
from objects.channel import Channel
from objects.beatmap import Beatmap
from constants.playmode import Gamemode, Mode
from starlette.routing import Router
from starlette.responses import Response
from packets.reader import Reader, Packet
from constants.packets import ClientPackets, ServerPackets
from constants.player import ActionStatus, Privileges
from starlette.requests import Request, ClientDisconnect
from utils.general import ORJSONResponse

from tasks import cache_allowed_osu_builds


def register_event(packet: ClientPackets, restricted: bool = False) -> Callable:
    def decorator(cb: Callable) -> None:
        services.packets |= {
            packet.value: Packet(packet=packet, callback=cb, restricted=restricted)
        }

    return decorator


bancho = Router()
IGNORED_PACKETS = (
    ClientPackets.PING,
    ClientPackets.RECEIVE_UPDATES,
    ClientPackets.SPECTATE_FRAMES,
)


@bancho.route("/", methods=["POST", "GET"])
async def handle_bancho(request: Request) -> Response:
    if request.method == "GET":
        online_players = len(services.players)
        uptime = time.time() - services.startup
        registered_players = await services.database.fetch_val(
            "SELECT COUNT(*) FROM users"
        )
        scores_amount = await services.redis.get("ragnarok:total_scores")
        accumulated_pp = await services.redis.get("ragnarok:total_pp")

        return ORJSONResponse(
            content={
                "uptime": uptime,
                "online_players": online_players,
                "multiplayer_rooms": len(services.matches),
                "registered_players": registered_players,
                "total_scores": int(scores_amount),
                "accumulated_pp": float(accumulated_pp),
            }
        )

    if (
        not "user-agent" in request.headers.keys()
        or request.headers["user-agent"] != "osu!"
    ):
        return Response(content=b"no")

    if not "osu-token" in request.headers:
        return await login(request)

    token = request.headers["osu-token"]

    # client has osu-token, but isn't saved in players cache
    # player either lost connection or the server restarted
    if not (player := services.players.get(token)):
        current_time = time.time()

        # the client has 20 seconds to reconnect
        if current_time - services.startup < 20:
            return Response(
                content=writer.notification("Server has restarted")
                + writer.server_restart()
            )

        return Response(
            content=writer.notification("You lost connection to the server!")
            + writer.server_restart()
        )

    try:
        body = await request.body()
    except ClientDisconnect:
        services.logger.info(f"{player.username} logged out.")
        await player.logout()

        return Response(content=player.dequeue())

    for packet in (sr := Reader(body)):
        if player.is_restricted and (not packet.restricted):
            continue

        elapsed_start = time.time_ns()

        await packet.callback(player, sr)

        elapsed = (time.time_ns() - elapsed_start) / 1e6

        if services.debug and packet.packet not in IGNORED_PACKETS:
            services.logger.debug(
                f"ClientPacket(id={packet.packet.value}, name={packet.packet.name}) has been requested by {player.username} - elapsed {elapsed:.2f}ms"
            )

    await player.update_latest_activity()

    return Response(content=player.dequeue())


ALREADY_ONLINE = "You're already online!"
RESTRICTED_MSG = "Your account has been set in restricted mode."


@unique
class LoginResponse(IntEnum):
    INCORRECT_LOGIN = -1
    INVALID_CLIENT = -2  # usually just too old
    # -3 is also lock client
    LOCK_CLIENT = -4
    SERVER_SIDE_ERROR = -5
    UNAUTHORIZED_CUTTING_EDGE_BUILD = -6
    PASSWORD_RESET = -7


def failed_login(code: LoginResponse, /, msg: str = "", extra: bytes = b"") -> Response:
    if msg:
        services.logger.warn(f"{msg} ({code.name})")

    return Response(
        content=writer.user_id(code.value) + extra, headers={"cho-token": "no"}
    )


async def login(req: Request) -> Response:
    response = bytearray(writer.protocol_version(19))
    body = await req.body()
    elapsed_start = time.time_ns()
    # parse login info and client info.
    # {0}
    login_info = body.decode().split("\n")[:-1]

    # {0}|{1}|{2}|{3}|{4}
    # 0 = Build name, 1 = Time offset
    # 2 = Display city location, 3 = Client hash
    # 4 = Block nonfriend PMs
    client_info = login_info[2].split("|")

    # the players ip address
    ip = req.headers["X-Real-IP"]

    user_info = await services.database.fetch_one(
        "SELECT username, id, privileges, passhash, lon, lat, "
        "country FROM users WHERE safe_username = :safe_uname ",
        {"safe_uname": login_info[0].lower().replace(" ", "_")},
    )

    if not user_info:
        return failed_login(
            LoginResponse.INCORRECT_LOGIN,
            msg=f'A user tried logging in with the username "{login_info[0]}", but the user doesn\'t exist.',
        )

    if services.osu_settings.server_maintenance.value and user_info["id"] != 3275:
        if not user_info["privileges"] & Privileges.DEVELOPER | Privileges.ADMIN:
            return failed_login(
                LoginResponse.UNAUTHORIZED_CUTTING_EDGE_BUILD,
                extra=writer.notification("Server is currently under maintenance."),
            )

        response += writer.notification(
            "Server is currently under maintenance. Remember to turn it off, when everything is done and ready."
        )

    # encode user password and input password.
    user_password = user_info["passhash"].encode("utf-8")
    password_md5 = login_info[1].encode("utf-8")

    # check if the password is correct
    if user_password in services.bcrypt_cache:
        if password_md5 != services.bcrypt_cache[user_password]:
            return failed_login(
                LoginResponse.INCORRECT_LOGIN,
                msg=f"{user_info['username']} ({user_info['id']}) tried logging in with the wrong password.",
            )
    else:
        if not bcrypt.checkpw(password_md5, user_password):
            return failed_login(
                LoginResponse.INCORRECT_LOGIN,
                msg=f"{user_info['username']} ({user_info['id']}) tried logging in with the wrong password.",
            )

        services.bcrypt_cache[user_password] = password_md5

    if target := services.players.get(user_info["username"]):
        timeago_format = datetime.fromtimestamp(target.last_update)
        return failed_login(
            LoginResponse.INCORRECT_LOGIN,
            msg=f"A user tried to sign in to {target!r} which is already online. "
            f"(last session update was {timeago.format(timeago_format)}))",
            extra=writer.notification(ALREADY_ONLINE),
        )

    # check if user is restricted
    if not user_info["privileges"] & Privileges.VERIFIED | Privileges.PENDING:
        response += writer.notification(RESTRICTED_MSG)

    # [1:] removes the little b infront of the version
    client_version = client_info[0][1:]

    if client_version not in services.ALLOWED_BUILDS and not client_version.endswith(
        "rina"
    ):
        # since allowed osu builds is cached from startup
        # we should check if there has been any new builds
        # since startup.
        await cache_allowed_osu_builds()

        # if again the client_info is not in `services.ALLOWED_BUILDS`
        # then return invalid client response.
        if client_version not in services.ALLOWED_BUILDS:
            return failed_login(LoginResponse.INVALID_CLIENT)

        services.logger.debug("allowed osu! builds cache has been updated.")

    # check if the user is banned.
    if user_info["privileges"] & Privileges.BANNED:
        return failed_login(
            LoginResponse.LOCK_CLIENT,  # should we really lock their client? lol
            msg=f"{user_info['username']} tried to login, but were unable to do so, since they're banned.",
        )

    security_info = client_info[3].split(":")

    # invalid security hash (old ver probably using that)
    if len(security_info) < 4:
        return failed_login(LoginResponse.INCORRECT_LOGIN)

    raw_mac_address = security_info[1]
    mac_address = security_info[2]
    unique_id = security_info[3]
    disk_id = security_info[4]

    linked_hardware = await services.database.fetch_one(
        "SELECT * FROM hwid_links WHERE mac_address = :mac_address "
        "OR unique_id = :unique_id OR disk_id = :disk_id",
        {"mac_address": mac_address, "unique_id": unique_id, "disk_id": disk_id},
    )

    if not linked_hardware:
        await services.database.execute(
            "INSERT INTO hwid_links (user_id, raw_mac_address, mac_address, unique_id, disk_id) "
            "VALUES (:user_id, :raw_mac_address, :mac_address, :unique_id, :disk_id)",
            {
                "user_id": user_info["id"],
                "raw_mac_address": raw_mac_address,
                "mac_address": mac_address,
                "unique_id": unique_id,
                "disk_id": disk_id,
            },
        )
    else:
        if linked_hardware["banned"]:
            return failed_login(
                LoginResponse.LOCK_CLIENT,
                msg=f"{user_info['username']} tried to login with banned hardware.",
            )

        mismatched_ids = []

        if linked_hardware["mac_address"] != mac_address:
            mismatched_ids.append("`mac_address`")

        if linked_hardware["unique_id"] != unique_id:
            mismatched_ids.append("`unique_id`")

        if linked_hardware["disk_id"] != disk_id:
            mismatched_ids.append("`disk_id`")

        if mismatched_ids:
            msg = f"{user_info['username']} ({user_info['id']}) has mismatched hardware ids. Mismatched IDs are {", ".join(mismatched_ids)}"

            services.logger.warning(msg)
            await services.bot.log(msg, type=LoggingType.HWID_CHECKS)

        # if the user, has matched someone elses
        if linked_hardware["user_id"] != user_info["id"]:
            response += writer.notification(
                "You have been caught logging in to another account on the same machine!\n\n"
                "If you believe this is a mistake, please contact either Aoba or Carlohman1. "
                "Nothing crucial will happen to your account other than the staffs has been notified and will check your account. "
                "If the staff finds you multiaccounting, it will lead to your main account getting restricted aswell as the one you're currently on."
            )

    kwargs = {
        "block_nonfriend": client_info[4],
        "version": client_info[0],
        "time_offset": int(client_info[1]),
        "ip": ip,
    }

    player = Player(**dict(user_info), **kwargs)
    player.last_update = time.time()

    services.players.add(player)

    await asyncio.gather(
        *[
            player.update_stats_cache(),
            player.get_friends(),
            player.get_achievements(),
            player.get_clan_tag(),
            player.verify(),
        ]
    )

    if user_info["country"] == "XX":
        await player.set_location()
        await player.save_location()

    services.loop.create_task(player.check_loc())

    # add user session data to redis
    await services.redis.hset(
        f"ragnarok:session:{player.id}",
        mapping={
            "token": player.token,
            "session_start": time.time(),
            ###
            "gamemode": player.gamemode.name,
            "mode": player.play_mode.name,
            ###
            "status": player.status.name,
            "status_text": player.status_text,
            "beatmap_id": player.map_id,
        },
    )  # type: ignore

    response += writer.user_id(player.id)
    response += writer.user_privileges(player.privileges)
    response += writer.friends_list(player.friends)
    response += writer.user_presence(player, spoof=True)
    response += writer.update_stats(player)

    for channel in services.channels:
        if channel.is_public:
            response += writer.channel_info(channel)

        if channel.is_staff and player.is_staff:
            response += writer.channel_info(channel)
            # data += writer.channel_join(chan.display_name)
            channel.connect(player)

    for target in services.players:
        # NOTE: current player don't need this
        #       because it has been sent already
        if target == player:
            continue

        target.enqueue(writer.user_presence(player) + writer.update_stats(player))

        if target.is_bot:
            response += writer.bot_presence()
        else:
            response += writer.user_presence(target)

        response += writer.update_stats(target)

    response += writer.channel_info_end()

    elapsed = (time.time_ns() - elapsed_start) / 1e6

    if services.osu_settings.welcome_message.value:
        # maybe add formatting to message?
        response += writer.notification(services.osu_settings.welcome_message.string)

    if player.privileges & Privileges.DEVELOPER:
        response += writer.notification(f"Authorization took {elapsed:.2f} ms.")

    services.logger.info(f"{player!r} logged in.")

    return Response(content=bytes(response), headers={"cho-token": player.token})


# id: 0
@register_event(ClientPackets.CHANGE_ACTION, restricted=True)
async def change_action(player: Player, sr: Reader) -> None:
    player.status = ActionStatus(sr.read_byte())
    status_text = sr.read_string()
    player.map_md5 = sr.read_string()
    player.current_mods = Mods(sr.read_uint32())
    player.play_mode = Mode(sr.read_byte())
    player.map_id = sr.read_int32()

    player.gamemode = (
        Gamemode.RELAX if player.current_mods & Mods.RELAX else Gamemode.VANILLA
    )

    player.status_text = f"{status_text.strip()} on {player.gamemode.name.lower()}"

    services.loop.create_task(player.update_stats_cache())

    await services.redis.hset(
        f"ragnarok:session:{player.id}",
        mapping={
            "gamemode": player.gamemode.name,
            "mode": player.play_mode.name,
            ###
            "status": player.status.name,
            "status_text": player.status_text,
            "beatmap_id": player.map_id,
        },
    )  # type: ignore

    if not player.is_restricted:
        services.players.enqueue(writer.update_stats(player))


async def _handle_command(channel: Channel, msg: str, player: Player):
    if resp := await cmd.handle_commands(message=msg, sender=player, reciever=channel):
        channel.send(resp, sender=services.bot)


# id: 1
@register_event(ClientPackets.SEND_PUBLIC_MESSAGE)
async def send_public_message(player: Player, sr: Reader) -> None:
    # sender; but unused since
    # we know who sent it lol
    sr.read_string()

    msg = sr.read_string()
    channel_name = sr.read_string()

    sr.read_int32()  # sender id

    if not msg or msg.isspace():
        return

    if channel_name == "#multiplayer":
        if not (match := player.match):
            services.logger.warn(
                f"{player.username} tried to send a message in #multiplayer, but they're not in a match."
            )
            return

        channel = match.chat
    elif channel_name == "#spectator":
        if player.spectators:
            channel = services.channels.get(f"#spect_{player.id}")
        elif player.spectating:
            channel = services.channels.get(f"#spect_{player.spectating.id}")
        else:
            channel = None
    else:
        channel = services.channels.get(channel_name)

    if not channel:
        player.shout(
            f"You can't send messages to a channel ({channel_name}), you're not already connected to."
        )
        return

    # send message to channel
    channel.send(msg, player)

    # check if the message is a np.
    # if so, post the 100%, 99%, etc.
    # pp for the map.
    if now_playing := services.regex["np"].search(msg):
        beatmap = await Beatmap.get_from_db(map_id=int(now_playing.group(1)))

        if not beatmap:
            player.shout(
                "beatmap not found, contact a developer about this with the beatmap link."
            )
            return

        player.last_np = beatmap
        services.loop.create_task(_handle_command(channel, "!pp ", player))

    # commands should be run on another thread
    # so slower commands don't stop the server.
    if msg[0] == services.prefix:
        services.loop.create_task(_handle_command(channel, msg, player))


# id: 2
@register_event(ClientPackets.LOGOUT, restricted=True)
async def logout(player: Player, sr: Reader) -> None:
    sr.read_int32()

    # osu tends to double send logout packet
    if (time.time() - player.login_time) < 1:
        return

    services.logger.info(f"{player.username} logged out.")

    await player.logout()


# id: 3
@register_event(ClientPackets.REQUEST_STATUS_UPDATE, restricted=True)
async def update_stats(player: Player, sr: Reader) -> None:
    # TODO: add this update for spectator as well
    #       since they need to have up-to-date beatmap info
    player.enqueue(writer.update_stats(player))


# # id: 4
@register_event(ClientPackets.PING, restricted=True)
async def pong(player: Player, sr: Reader) -> None:
    player.enqueue(writer.pong())


# id: 16
@register_event(ClientPackets.START_SPECTATING)
async def start_spectate(player: Player, sr: Reader) -> None:
    spectating_id = sr.read_int32()
    host = services.players.get(spectating_id)

    if not host:
        return

    host.add_spectator(player)


# id: 17
@register_event(ClientPackets.STOP_SPECTATING)
async def stop_spectate(player: Player, sr: Reader) -> None:
    host = player.spectating

    if not host:
        services.logger.critical(
            f"{player.username} requested STOP_SPECTATING client "
            "packet, but they're not spectating any player."
        )
        return

    host.remove_spectator(player)


# id: 18
@register_event(ClientPackets.SPECTATE_FRAMES)
async def spectating_frames(player: Player, sr: Reader) -> None:
    # TODO: make a proper R/W instead of echoing like this
    # frame = sr.read_spectate_packet()
    frame = sr.read_raw()

    # packing manually seems to be faster, so let's use that.
    data = struct.pack("<HxI", ServerPackets.SPECTATE_FRAMES, len(frame)) + frame

    for spectator in player.spectators:
        # to prevent double frames
        if spectator is not player:
            spectator.enqueue(data)


# id: 21
@register_event(ClientPackets.CANT_SPECTATE)
async def unable_to_spec(player: Player, sr: Reader) -> None:
    response = writer.spectator_cant_spectate(player.id)

    if not (host := player.spectating):
        return

    host.enqueue(response)

    for spectator in host.spectators:
        spectator.enqueue(response)


# id: 25
@register_event(ClientPackets.SEND_PRIVATE_MESSAGE)
async def send_private_message(player: Player, sr: Reader) -> None:
    # sender - but unused, since we already know
    # who the sender is lol
    sr.read_string()

    msg = sr.read_string()
    recipent_id = sr.read_string()

    sr.read_int32()  # sender id

    if not (recipent := services.players.get(recipent_id)):
        player.shout("The player you're trying to reach is currently offline.")
        return

    if not recipent.is_bot:
        player.send(msg, recipent)
    else:
        if now_playing := services.regex["np"].search(msg):
            beatmap = await Beatmap.get(map_id=int(now_playing.group(1)))

            if not beatmap:
                return

            player.last_np = beatmap

        if msg[0] == services.prefix:
            if response := await cmd.handle_commands(
                message=msg, sender=player, reciever=services.bot
            ):
                services.bot.send(response, player)
                return

        services.bot.send("beep boop", player)


# id: 29
@register_event(ClientPackets.PART_LOBBY)
async def lobby_part(player: Player, sr: Reader) -> None:
    player.in_lobby = False


# id: 30
@register_event(ClientPackets.JOIN_LOBBY)
async def lobby_join(player: Player, sr: Reader) -> None:
    player.in_lobby = True

    if player.match:
        player.leave_match()

    for match in services.matches:
        if match.connected:
            player.enqueue(writer.match(match))


# id: 31
@register_event(ClientPackets.CREATE_MATCH)
async def mp_create_match(player: Player, sr: Reader) -> None:
    match = await sr.read_match()
    services.matches.add(match)
    player.join_match(match, password=match.password)


# id: 32
@register_event(ClientPackets.JOIN_MATCH)
async def mp_join(player: Player, sr: Reader) -> None:
    match_id = sr.read_int32()
    match = services.matches.get(match_id)

    match_password = sr.read_string()

    if player.match or not match:
        player.enqueue(writer.match_fail())
        return

    player.join_match(match, password=match_password)


# id: 33
@register_event(ClientPackets.PART_MATCH)
async def mp_leave(player: Player, sr: Reader) -> None:
    if player.match:
        player.leave_match()


# id: 38
@register_event(ClientPackets.MATCH_CHANGE_SLOT)
async def mp_change_slot(p: Player, sr: Reader) -> None:
    slot_id = sr.read_int32()
    match = p.match

    if not match or match.in_progress:
        return

    slot = match.slots[slot_id]

    if slot.status.is_occupied:
        services.logger.error(
            f"{p.username} tried to change to an occupied slot ({match!r})"
        )
        return

    if not (old_slot := match.find_user(p)):
        return

    slot.copy_from(old_slot)

    old_slot.reset()

    match.enqueue_state()


# id: 39
@register_event(ClientPackets.MATCH_READY)
async def mp_ready_up(player: Player, sr: Reader) -> None:
    match = player.match

    if not match or match.in_progress:
        services.logger.critical(
            f"{player.username} requested MATCH_READY packet, "
            "but they're not in a match or the match is already in progress."
        )
        return

    if not (slot := match.find_user(player)):
        services.logger.critical(
            f"{match}: {player.username} should be in the match, but couldn't be found."
        )
        return

    if slot.status == SlotStatus.READY:
        return

    slot.status = SlotStatus.READY

    match.enqueue_state()


# id: 40
@register_event(ClientPackets.MATCH_LOCK)
async def mp_lock_slot(player: Player, sr: Reader) -> None:
    slot_id = sr.read_int32()
    match = player.match

    if not match or match.in_progress:
        return

    slot = match.find_slot(slot_id)

    if not slot:
        services.logger.critical(
            f"{player.username} tried to lock a slot out of bounds."
        )
        return

    if slot.status == SlotStatus.LOCKED:
        slot.status = SlotStatus.OPEN
    else:
        slot.status = SlotStatus.LOCKED

    match.enqueue_state()


# id: 41
@register_event(ClientPackets.MATCH_CHANGE_SETTINGS)
async def mp_change_settings(player: Player, sr: Reader) -> None:
    match = player.match

    if not match or match.in_progress:
        services.logger.critical(
            f"{player.username} requested MATCH_CHANGE_SETTINGS packet, "
            "but they're not in a match or the match is already in progress."
        )
        return

    updated_match = await sr.read_match()

    if match.host != player.id:
        services.logger.warn(
            f"{player.username} tried to change the "
            "match settings, but they're not the host."
        )
        return

    if updated_match.map is not None and match.map is not None:
        if updated_match.map.map_md5 != match.map.map_md5:
            match.map = updated_match.map
            match.mode = Mode(updated_match.mode)

            # announce the pp for 100%, 99%, etc. for the chosen map with chosen mods.
            await _handle_command(match.chat, f"!pp [MULTI]", player)

    if updated_match.name != match.name:
        match.name = updated_match.name

    if updated_match.freemods != match.freemods:
        if updated_match.freemods:
            match.mods = Mods(match.mods & Mods.MULTIPLAYER)
        else:
            for slot in match.slots:
                if slot.mods:
                    slot.mods = Mods.NONE

        match.freemods = updated_match.freemods

    if updated_match.scoring_type != match.scoring_type:
        match.scoring_type = updated_match.scoring_type

    if updated_match.team_type != match.team_type:
        match.team_type = updated_match.team_type

    match.enqueue_state()


# id: 44
@register_event(ClientPackets.MATCH_START)
async def mp_start(player: Player, sr: Reader) -> None:
    match = player.match

    if not match or match.in_progress:
        services.logger.critical(
            f"{player.username} requested MATCH_START packet, "
            "but they're not in a match or the match is already in progress."
        )
        return

    if player.id != match.host:
        services.logger.warn(
            f"{player.username} tried to start the match, while not being the host."
        )
        return

    for slot in match.slots:
        if slot.status.is_occupied:
            if slot.player is not None and slot.status != SlotStatus.NOMAP:
                slot.status = SlotStatus.PLAYING
                slot.player.enqueue(writer.match_start(match))

    match.in_progress = True

    match.enqueue_state(lobby=True)


# id: 47
@register_event(ClientPackets.MATCH_SCORE_UPDATE)
async def mp_score_update(player: Player, sr: Reader) -> None:
    match = player.match

    if not match:
        services.logger.critical(
            f"{player.username} requested MATCH_SCORE_UPDATE packet, but they're not in a match."
        )
        return

    raw_sr = copy.copy(sr)

    raw = raw_sr.read_raw()
    score_frame = sr.read_score_frame()

    if match.pp_win_condition and match.map is not None:
        if os.path.isfile(f".data/beatmaps/{match.map.map_id}.osu"):
            # should not happen
            if not (slot := match.find_user(player)):
                return

            bmap = BMap(path=f".data/beatmaps/{match.map.map_id}.osu")

            if bmap.mode != match.mode:
                bmap.convert(GameMode(match.mode.value))

            calc = Performance(
                n300=score_frame.count_300,
                n100=score_frame.count_100,
                n50=score_frame.count_50,
                n_geki=score_frame.count_geki,
                n_katu=score_frame.count_katu,
                combo=score_frame.max_combo,
                misses=score_frame.count_miss,
                mods=slot.mods | match.mods,
            ).calculate(bmap)

            pp = calc.pp

            if math.isnan(pp) or math.isinf(pp):
                pp = 0

            score_frame.score = round(pp)
        else:
            services.logger.critical(
                f"{match!r}: Failed to update pp, because the .osu file doesn't exist."
            )

    if (slot_id := match.find_user_slot(player)) is None:
        return

    match.enqueue(writer.match_score_update(score_frame, slot_id, raw))


# id: 49
@register_event(ClientPackets.MATCH_COMPLETE)
async def mp_complete(player: Player, sr: Reader) -> None:
    match = player.match

    if not match or not match.in_progress:
        services.logger.critical(
            f"{player.username} requested MATCH_COMPLETE packet, "
            "but they're not in a match or the match is not in progress."
        )
        return

    players_played = [
        slot.player
        for slot in match.slots
        if slot.status == SlotStatus.PLAYING and slot.player is not None
    ]

    for slot in match.slots:
        if slot.player in players_played:
            slot.status = SlotStatus.NOTREADY

    match.in_progress = False

    for slot in match.slots:
        if slot.status.is_occupied and slot.status != SlotStatus.NOMAP:
            slot.status = SlotStatus.NOTREADY

        slot.skipped = False
        slot.loaded = False

    match.enqueue_state(lobby=True)

    for player in players_played:
        player.enqueue(writer.match_complete())

    match.enqueue_state(lobby=True)


# id: 51
@register_event(ClientPackets.MATCH_CHANGE_MODS)
async def mp_change_mods(player: Player, sr: Reader) -> None:
    mods = Mods(sr.read_int32())
    match = player.match

    if not match or match.in_progress:
        services.logger.critical(
            f"{player.username} requested MATCH_CHANGE_MODS packet, "
            "but they're not in a match or the match is already in progress."
        )
        return

    if match.freemods:
        if match.host == player.id:
            match.mods = Mods(mods & Mods.MULTIPLAYER)

            for slot in match.slots:
                if slot.status == SlotStatus.READY:
                    slot.status = SlotStatus.NOTREADY

        if not (slot := match.find_user(player)):
            return

        slot.mods = Mods(mods & ~Mods.MULTIPLAYER)
    else:
        if match.host != player.id:
            services.logger.critical(
                f"{match!r}: {player.username} tried change the match's mods."
            )
            return

        match.mods = Mods(mods)

        for slot in match.slots:
            if slot.status.is_occupied and slot.status != SlotStatus.NOMAP:
                slot.status = SlotStatus.NOTREADY

    match.enqueue_state()


# id: 52
@register_event(ClientPackets.MATCH_LOAD_COMPLETE)
async def mp_load_complete(player: Player, sr: Reader) -> None:
    match = player.match

    if not match or not match.in_progress:
        services.logger.critical(
            f"{player.username} requested MATCH_LOAD_COMPLETE packet, "
            "but they're not in a match or the match is not in progress."
        )
        return

    if not (slot := match.find_user(player)):
        return

    slot.loaded = True

    if all(s.loaded for s in match.slots if s.status == SlotStatus.PLAYING):
        match.enqueue(writer.match_all_ready())


# id: 54
@register_event(ClientPackets.MATCH_NO_BEATMAP)
async def mp_no_beatmap(player: Player, sr: Reader) -> None:
    match = player.match

    if not match:
        services.logger.critical(
            f"{player.username} requested MATCH_NO_BEATMAP packet, but they're not in a match."
        )
        return

    if not (slot := match.find_user(player)):
        return

    slot.status = SlotStatus.NOMAP

    match.enqueue_state()


# id: 55
@register_event(ClientPackets.MATCH_NOT_READY)
async def mp_unready(player: Player, sr: Reader) -> None:
    match = player.match

    if not match:
        services.logger.critical(
            f"{player.username} requested MATCH_NOT_READY packet, but they're not in a match."
        )
        return

    if not (slot := match.find_user(player)):
        return

    if slot.status == SlotStatus.NOTREADY:
        return

    slot.status = SlotStatus.NOTREADY

    match.enqueue_state()


# id: 56
@register_event(ClientPackets.MATCH_FAILED)
async def match_failed(player: Player, sr: Reader) -> None:
    match = player.match

    if not match or not match.in_progress:
        services.logger.critical(
            f"{player.username} requested MATCH_FAILED packet, "
            "but they're not in a match or the match is not in progress."
        )
        return

    for slot in match.slots:
        if slot.player is not None:
            slot.player.enqueue(writer.match_player_failed(player.id))


# id: 59
@register_event(ClientPackets.MATCH_HAS_BEATMAP)
async def has_beatmap(player: Player, sr: Reader) -> None:
    match = player.match

    if not match:
        services.logger.critical(
            f"{player.username} requested MATCH_HAS_BEATMAP packet, but they're not in a match."
        )
        return

    if not (slot := match.find_user(player)):
        return

    slot.status = SlotStatus.NOTREADY

    match.enqueue_state()


# id: 60
@register_event(ClientPackets.MATCH_SKIP_REQUEST)
async def skip_request(player: Player, sr: Reader) -> None:
    match = player.match

    if not match or not match.in_progress:
        services.logger.critical(
            f"{player.username} requested MATCH_SKIP_REQUEST packet, "
            "but they're not in a match or the match is not in progress."
        )
        return

    if not (slot := match.find_user(player)):
        return

    if slot.skipped:
        return

    slot.skipped = True
    match.enqueue(writer.match_player_skipped(player.id))

    for slot in match.slots:
        if slot.status == SlotStatus.PLAYING and not slot.skipped:
            return

    match.enqueue(writer.match_skip())


# id: 63
@register_event(ClientPackets.CHANNEL_JOIN, restricted=True)
async def join_channel(player: Player, sr: Reader) -> None:
    channel_name = sr.read_string()
    channel = services.channels.get(channel_name)

    if not channel:
        player.shout(f"{channel_name} couldn't be found.")
        services.logger.warn(
            f"{player.username} tried to join {channel_name}, but it doesn't exist."
        )
        return

    channel.connect(player)


# id: 70
@register_event(ClientPackets.MATCH_TRANSFER_HOST)
async def mp_transfer_host(player: Player, sr: Reader) -> None:
    if not (match := player.match):
        services.logger.critical(
            f"{player.username} requested MATCH_NOT_READY packet, but they're not in a match."
        )
        return

    slot_id = sr.read_int32()

    if not (slot := match.find_slot(slot_id)):
        return

    if slot.player is None:
        return

    match.host = slot.player.id
    slot.player.enqueue(writer.match_transfer_host())

    match.enqueue(writer.notification(f"{slot.player.username} became host!"))
    match.enqueue_state()


# id: 73 and 74
@register_event(ClientPackets.FRIEND_REMOVE, restricted=True)
@register_event(ClientPackets.FRIEND_ADD, restricted=True)
async def handle_friend(player: Player, sr: Reader) -> None:
    await player.handle_friend(sr.read_int32())


# id: 77
@register_event(ClientPackets.MATCH_CHANGE_TEAM)
async def mp_change_team(player: Player, sr: Reader) -> None:
    match = player.match

    if not match or match.in_progress:
        services.logger.critical(
            f"{player.username} requested MATCH_CHANGE_TEAM packet, "
            "but they're not in a match or the match is already in progress."
        )
        return

    if not (slot := match.find_user(player)):
        return

    if slot.team == SlotTeams.BLUE:
        slot.team = SlotTeams.RED
    else:
        slot.team = SlotTeams.BLUE

    # Should this really be for every occupied slot? or just the user changing team?
    for slot in match.slots:
        if slot.status.is_occupied and slot.status != SlotStatus.NOMAP:
            slot.status = SlotStatus.NOTREADY

    match.enqueue_state()


# id: 78
@register_event(ClientPackets.CHANNEL_PART, restricted=True)
async def part_channel(player: Player, sr: Reader) -> None:
    channel_name = sr.read_string()

    # if the channel_name doesn't start with "#",
    # it means, they're parting from DM, which is
    # already handled client-side.
    if channel_name[0] != "#":
        return

    if not (channel := services.channels.get(channel_name)):
        services.logger.warn(
            f"{player.username} tried to part from {channel_name}, but channel doesn't exist."
        )
        return

    channel.disconnect(player)


# id: 85
@register_event(ClientPackets.USER_STATS_REQUEST, restricted=True)
async def request_stats(player: Player, sr: Reader) -> None:
    # people id's that current online rn
    user_ids = sr.read_int32_list()

    if len(user_ids) > 32:
        return

    for user_id in user_ids:
        if user_id == player.id:
            continue

        if not (target := services.players.get(user_id)):
            continue

        target.enqueue(writer.update_stats(target))


# id: 87
@register_event(ClientPackets.MATCH_INVITE)
async def mp_invite(player: Player, sr: Reader) -> None:
    if not (match := player.match):
        services.logger.critical(
            f"{player.username} requested MATCH_NOT_READY packet, but they're not in a match."
        )
        return

    recipent_id = sr.read_int32()

    if not (recipent := services.players.get(recipent_id)):
        player.shout("You can't invite someone who's offline.")
        return

    player.send(
        f"Come join my multiplayer match: {match.embed}",
        recipent,
    )


# id: 90
@register_event(ClientPackets.MATCH_CHANGE_PASSWORD)
async def change_pass(player: Player, sr: Reader) -> None:
    match = player.match

    if not match or match.in_progress:
        services.logger.critical(
            f"{player.username} requested MATCH_CHANGE_PASSWORD packet, "
            "but they're not in a match or the match is already in progress."
        )
        return

    updated_match = await sr.read_match()

    if match.password == updated_match.password:
        return

    match.password = updated_match.password

    for slot in match.slots:
        if slot.player is not None and slot.status.is_occupied:
            slot.player.enqueue(writer.match_change_password(updated_match.password))

    match.enqueue_state(lobby=True)


# id: 97
@register_event(ClientPackets.USER_PRESENCE_REQUEST, restricted=True)
async def request_presence(player: Player, sr: Reader) -> None:
    # people id's that current online rn
    user_ids = sr.read_int32_list()

    if len(user_ids) > 256:
        return

    for user_id in user_ids:
        if user_id == player.id:
            continue

        if not (target := services.players.get(user_id)):
            continue

        if target.is_bot:
            player.enqueue(writer.bot_presence())
        else:
            player.enqueue(writer.user_presence(target))


# id: 98
@register_event(ClientPackets.USER_PRESENCE_REQUEST_ALL, restricted=True)
async def request_presence_all(_: Player, sr: Reader) -> None:
    sr.read_int32()

    for player in services.players:
        player.enqueue(writer.user_presence(player))

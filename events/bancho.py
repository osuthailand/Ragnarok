from enum import IntEnum
import os
import time
import copy
import bcrypt
import struct
import asyncio
import math

from utils import log
from utils import general
from packets import writer
from typing import Callable
from objects import services
from constants import commands as cmd
from rina_pp_pyb import Calculator, Beatmap as BMap

from constants.match import *
from constants.mods import Mods
from objects.player import Player
from objects.channel import Channel
from objects.beatmap import Beatmap
from constants.playmode import Gamemode, Mode
from starlette.routing import Router
from starlette.responses import Response
from packets.reader import Reader, Packet
from constants.packets import BanchoPackets
from constants.player import bStatus, Privileges
from starlette.requests import Request, ClientDisconnect


def register_event(packet: BanchoPackets, restricted: bool = False) -> Callable:
    def decorator(cb: Callable) -> None:
        services.packets |= {
            packet.value: Packet(
                packet=packet, callback=cb, restricted=restricted)
        }

    return decorator


bancho = Router()
IGNORED_PACKETS = (BanchoPackets.OSU_PING, BanchoPackets.OSU_RECEIVE_UPDATES, BanchoPackets.OSU_SPECTATE_FRAMES)


@bancho.route("/", methods=["POST", "GET"])
async def handle_bancho(req: Request) -> Response:
    if req.method == "GET":
        msg = services.title_card
        online_players = len(services.players)
        msg += f"\ncurrently {online_players} players online"

        return Response(content=msg.encode())

    if not "user-agent" in req.headers.keys() or req.headers["user-agent"] != "osu!":
        return Response(content=b"no")

    if not "osu-token" in req.headers:
        return await login(req)

    token = req.headers["osu-token"]

    if not (player := services.players.get(token)):
        return Response(
            content=writer.notification("Server has restarted")
                    + writer.server_restart()
        )

    try:
        body = await req.body()
    except ClientDisconnect:
        log.info(f"{player.username} logged out.")
        player.logout()

        return Response(content=player.dequeue())

    for p in (sr := Reader(body)):
        if player.is_restricted and (not p.restricted):
            continue

        start = time.time_ns()

        await p.callback(player, sr)

        end = (time.time_ns() - start) / 1e6

        if services.debug and p.packet not in IGNORED_PACKETS:
            log.debug(
                f"Packet(id={p.packet.value}, name={p.packet.name}) has been requested by {
                    player.username} - {end:.2f}ms"
            )

    player.last_update = time.time()

    return Response(content=player.dequeue())


ALREADY_ONLINE = "You're already online!"
RESTRICTED_MSG = "Your account has been set in restricted mode."


@unique
class LoginResponse(IntEnum):
    INCORRECT_LOGIN = -1
    INVALID_CLIENT = -2 # usually just too old
    # -3 is also lock client
    LOCK_CLIENT = -4
    BANNED_HWID = -5
    UNAUTHORIZED_CUTTING_EDGE_BUILD = -6
    PASSWORD_RESET = -7



def failed_login(code: LoginResponse, /, extra: bytes = b"") -> Response:
    return Response(
        content=writer.user_id(code.value) + extra, headers={"cho-token": "no"}
    )


async def login(req: Request) -> Response:
    data = bytearray(writer.protocol_version(19))
    body = await req.body()
    start = time.time_ns()
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

    if services.osu_settings.server_maintenance.value:
        return failed_login(
            LoginResponse.UNAUTHORIZED_CUTTING_EDGE_BUILD, 
            extra=writer.notification("Server is currently under maintenance."))

    # get all user needed information
    if not (
        user_info := await services.sql.fetch(
            "SELECT username, id, privileges, "
            "passhash, lon, lat, country FROM users "
            "WHERE safe_username = %s",
            [login_info[0].lower().replace(" ", "_")],
        )
    ):
        return failed_login(-1)

    # encode user password and input password.
    phash = user_info["passhash"].encode("utf-8")
    pmd5 = login_info[1].encode("utf-8")

    # check if the password is correct
    if phash in services.bcrypt_cache:
        if pmd5 != services.bcrypt_cache[phash]:
            log.warn(
                f"USER {user_info['username']} ({user_info['id']}) | Login fail. (WRONG PASSWORD)"
            )

            return failed_login(LoginResponse.INCORRECT_LOGIN)
    else:
        if not bcrypt.checkpw(pmd5, phash):
            log.warn(
                f"USER {user_info['username']} ({user_info['id']}) | Login fail. (WRONG PASSWORD)"
            )

            return failed_login(LoginResponse.INCORRECT_LOGIN)

        services.bcrypt_cache[phash] = pmd5

    if _p := services.players.get(user_info["username"]):
        # user is already online? sus
        log.warn(
            f"A user tried to login onto the account {
                _p.username} ({_p.id}), but user already online."
        )
        return failed_login(LoginResponse.INCORRECT_LOGIN, extra=writer.notification(ALREADY_ONLINE))

    # invalid security hash (old ver probably using that)
    if len(client_info[3].split(":")) < 4:
        return failed_login(LoginResponse.INCORRECT_LOGIN)

    # check if user is restricted; pretty sure its like this lol
    if not user_info["privileges"] & Privileges.VERIFIED | Privileges.PENDING:
        data += writer.notification(RESTRICTED_MSG)

    # TODO: actual implement this check properly wtf
    # only allow 2023 clients
    # if not client_info[0].startswith("b2023"):
    #     return failed_login(LoginResponse.INVALID_CLIENT)

    # check if the user is banned.
    if user_info["privileges"] & Privileges.BANNED:
        log.info(
            f"{user_info['username']} tried to login, but failed to do so, since they're banned."
        )

        return failed_login(LoginResponse.LOCK_CLIENT)

    # TODO: hwid checks

    # TODO: Hardware ban check (security[3] and [4])
    """
    if (UserManager.CheckBannedHardwareId(securityHashParts[3], securityHashParts[4]))
    {
        SendRequest(RequestType.Bancho_LoginReply, new bInt(-5));
        return false;
    }
    """
    # if my_balls > sussy_balls:
    #   return BanchoResponse(await writer.UserID(-5))

    kwargs = {
        "block_nonfriend": client_info[4],
        "version": client_info[0],
        "time_offset": int(client_info[1]),
        "ip": ip,
    }

    p = Player(**user_info, **kwargs)
    p.last_update = time.time()

    services.players.add(p)

    await asyncio.gather(
        *[p.get_friends(), p.update_stats_cache(), p.get_achievements(), p.get_clan_tag()]
    )

    if not p.is_verified:
        services.bot.send_message(
            "Since we're still in beta, you'll need to verify your account with a beta key given by one of the founders. "
            "You'll have 30 minutes to verify the account, or the account will be deleted. "
            "To verify your account, please enter !verify <your beta key>",
            reciever=p,
        )

    if not (user_info["lon"] or user_info["lat"]) or user_info["country"] == "XX":
        await p.set_location()
        await p.save_location()

    asyncio.create_task(p.check_loc())

    data += writer.user_id(p.id)
    data += writer.user_privileges(p.privileges)

    if services.osu_settings.osu_menu_icon.value:
        data += writer.main_menu_icon(
            image_url=services.osu_settings.osu_menu_icon.string,
            url=f"https://{services.domain}",
        )

    data += writer.friends_list(p.friends)
    data += writer.user_presence(p, spoof=True)
    data += writer.update_stats(p)

    for chan in services.channels:
        if chan.public:
            data += writer.channel_info(chan)

        if chan.is_staff and p.is_staff:
            data += writer.channel_info(chan)
            # data += writer.channel_join(chan.display_name)
            chan.connect(p)

    for player in services.players:
        # NOTE: current player don't need this
        #       because it has been sent already
        if player == p:
            continue

        player.enqueue(writer.user_presence(p) + writer.update_stats(p))

        if player.bot:
            data += writer.bot_presence()
        else:
            data += writer.user_presence(player)

        data += writer.update_stats(player)

    data += writer.channel_info_end()

    et = (time.time_ns() - start) / 1e6

    if services.osu_settings.welcome_message.value:
        # maybe add formatting to message?
        data += writer.notification(services.osu_settings.welcome_message.string)

    data += writer.notification(f"Authorization took {et:.2f} ms.")

    log.info(f"{p!r} logged in.")

    return Response(content=bytes(data), headers={"cho-token": p.token})


# id: 0
@register_event(BanchoPackets.OSU_CHANGE_ACTION, restricted=True)
async def change_action(p: Player, sr: Reader) -> None:
    p.status = bStatus(sr.read_byte())
    status_text = sr.read_str()
    p.beatmap_md5 = sr.read_str()
    p.current_mods = Mods(sr.read_uint32())
    p.play_mode = Mode(sr.read_byte())
    p.beatmap_id = sr.read_int32()

    p.gamemode = (
        Gamemode.RELAX if p.current_mods & Mods.RELAX else
        Gamemode.AUTOPILOT if p.current_mods & Mods.AUTOPILOT else
        Gamemode.VANILLA
    )

    p.status_text = f"{status_text.strip()} on {p.gamemode.name.lower()}"

    asyncio.create_task(p.update_stats_cache())

    if not p.is_restricted:
        services.players.enqueue(writer.update_stats(p))


async def _handle_command(chan: Channel, msg: str, p: Player):
    if resp := await cmd.handle_commands(message=msg, sender=p, reciever=chan):
        chan.send(resp, sender=services.bot)


# id: 1
@register_event(BanchoPackets.OSU_SEND_PUBLIC_MESSAGE)
async def send_public_message(p: Player, sr: Reader) -> None:
    # sender; but unused since
    # we know who sent it lol
    sr.read_str()

    msg = sr.read_str()
    chan_name = sr.read_str()

    sr.read_int32()  # sender id

    if not p.is_verified:
        return

    if not msg or msg.isspace():
        return

    if chan_name == "#multiplayer":
        if not (match := p.match):
            return

        chan = match.chat
    elif chan_name == "#spectator":
        if p.spectators:
            chan = services.channels.get(f"#spect_{p.id}")
        elif p.spectating:
            chan = services.channels.get(f"#spect_{p.spectating.id}")
        else:
            chan = None
    else:
        chan = services.channels.get(chan_name)

    if not chan:
        p.shout(
            f"You can't send messages to a channel ({chan_name}), you're not already connected to."
        )
        return

    # send message to channel
    chan.send(msg, p)

    # check if the message is a np.
    # if so, post the 100%, 99%, etc.
    # pp for the map.
    if np := services.regex["np"].search(msg):
        log.info(np.groups())
        p.last_np = await Beatmap._get_beatmap_from_sql("", np.groups(0), 0)
        asyncio.create_task(_handle_command(chan, "!pp ", p))

    # this is for whenever the user failed to 
    # do a command with following arguments
    #
    # might remove this feature, as i don't see
    # a big use for it...
    if p.token in services.await_response and not services.await_response[p.token]:
        services.await_response[p.token] = msg

    # commands should be run on another thread
    # so slower commands (pp recalc) don't stop
    # the server.
    if msg[0] == services.prefix:
        asyncio.create_task(_handle_command(chan, msg, p))


# id: 2
@register_event(BanchoPackets.OSU_LOGOUT, restricted=True)
async def logout(p: Player, sr: Reader) -> None:
    _ = sr.read_int32()

    # osu tends to double send logout packet
    if (time.time() - p.login_time) < 1:
        return

    log.info(f"{p.username} logged out.")

    p.logout()


# id: 3
@register_event(BanchoPackets.OSU_REQUEST_STATUS_UPDATE, restricted=True)
async def update_stats(p: Player, sr: Reader) -> None:
    # TODO: add this update for spectator as well
    #       since they need to have up-to-date beatmap info
    p.enqueue(writer.update_stats(p))


# id: 4
@register_event(BanchoPackets.OSU_PING, restricted=True)
async def pong(p: Player, sr: Reader) -> None:
    p.enqueue(writer.pong())


# id: 16
@register_event(BanchoPackets.OSU_START_SPECTATING)
async def start_spectate(p: Player, sr: Reader) -> None:
    spec = sr.read_int32()
    host = services.players.get(spec)

    if not p.is_verified or not host:
        return

    host.add_spectator(p)


# id: 17
@register_event(BanchoPackets.OSU_STOP_SPECTATING)
async def stop_spectate(p: Player, sr: Reader) -> None:
    host = p.spectating

    if not host:
        return

    host.remove_spectator(p)


# id: 18
@register_event(BanchoPackets.OSU_SPECTATE_FRAMES)
async def spectating_frames(p: Player, sr: Reader) -> None:
    # TODO: make a proper R/W instead of echoing like this
    # frame = sr.read_spectate_packet()
    frame = sr.read_raw()

    # packing manually seems to be faster, so let's use that.
    data = struct.pack(
        "<HxI", BanchoPackets.CHO_SPECTATE_FRAMES, len(frame)) + frame

    for t in p.spectators:
        # to prevent double frames
        if t is not p:
            t.enqueue(data)


# id: 21
@register_event(BanchoPackets.OSU_CANT_SPECTATE)
async def unable_to_spec(p: Player, sr: Reader) -> None:
    ret = writer.spectator_cant_spectate(p.id)

    host = p.spectating
    host.enqueue(ret)

    for t in host.spectators:
        t.enqueue(ret)


# id: 25
@register_event(BanchoPackets.OSU_SEND_PRIVATE_MESSAGE)
async def send_private_message(p: Player, sr: Reader) -> None:
    # sender - but unused, since we already know
    # who the sender is lol
    sr.read_str()

    msg = sr.read_str()
    recieverr = sr.read_str()

    sr.read_int32()  # sender id

    if not (reciever := services.players.get(recieverr)):
        p.shout("The player you're trying to reach is currently offline.")
        return

    if not reciever.bot:
        p.send_message(msg, reciever=reciever)
    else:
        if np := services.regex["np"].search(msg):
            p.last_np = await Beatmap.get_beatmap(beatmap_id=np.groups(1)[0])

        if msg[0] == services.prefix:
            if resp := await cmd.handle_commands(
                message=msg, sender=p, reciever=services.bot
            ):
                services.bot.send_message(resp, reciever=p)
                return

        services.bot.send_message("beep boop", reciever=p)


# id: 29
@register_event(BanchoPackets.OSU_PART_LOBBY)
async def lobby_part(p: Player, sr: Reader) -> None:
    p.in_lobby = False


# id: 30
@register_event(BanchoPackets.OSU_JOIN_LOBBY)
async def lobby_join(p: Player, sr: Reader) -> None:
    p.in_lobby = True

    if not p.is_verified:
        return

    if p.match:
        p.leave_match()

    for match in services.matches:
        if match.connected:
            p.enqueue(writer.match(match))


# id: 31
@register_event(BanchoPackets.OSU_CREATE_MATCH)
async def mp_create_match(p: Player, sr: Reader) -> None:
    m = await sr.read_match()

    services.matches.add(m)

    p.join_match(m, pwd=m.match_pass)


# id: 32
@register_event(BanchoPackets.OSU_JOIN_MATCH)
async def mp_join(p: Player, sr: Reader) -> None:
    matchid = sr.read_int32()
    matchpass = sr.read_str()

    if p.match or not (m := services.matches.get(matchid)):
        p.enqueue(writer.match_fail())
        return

    p.join_match(m, pwd=matchpass)


# id: 33
@register_event(BanchoPackets.OSU_PART_MATCH)
async def mp_leave(p: Player, sr: Reader) -> None:
    if p.match:
        p.leave_match()


# id: 38
@register_event(BanchoPackets.OSU_MATCH_CHANGE_SLOT)
async def mp_change_slot(p: Player, sr: Reader) -> None:
    slot_id = sr.read_int32()

    if not (m := p.match) or m.in_progress:
        return

    slot = m.slots[slot_id]

    if slot.status == SlotStatus.OCCUPIED:
        log.error(f"{p.username} tried to change to an occupied slot ({m!r})")
        return

    if not (old_slot := m.find_user(p)):
        return

    slot.copy_from(old_slot)

    old_slot.reset()

    m.enqueue_state()


# id: 39
@register_event(BanchoPackets.OSU_MATCH_READY)
async def mp_ready_up(p: Player, sr: Reader) -> None:
    if not (m := p.match) or m.in_progress:
        return

    if not (slot := m.find_user(p)):
        log.debug("Slot not found?")
        return

    if slot.status == SlotStatus.READY:
        return

    slot.status = SlotStatus.READY

    m.enqueue_state()


# id: 40
@register_event(BanchoPackets.OSU_MATCH_LOCK)
async def mp_lock_slot(p: Player, sr: Reader) -> None:
    slot_id = sr.read_int32()

    if not (m := p.match) or m.in_progress:
        return

    slot = m.slots[slot_id]

    if slot.status == SlotStatus.LOCKED:
        slot.status = SlotStatus.OPEN
    else:
        slot.status = SlotStatus.LOCKED

    m.enqueue_state()


# id: 41
@register_event(BanchoPackets.OSU_MATCH_CHANGE_SETTINGS)
async def mp_change_settings(p: Player, sr: Reader) -> None:
    if not (m := p.match) or m.in_progress:
        return

    new_match = await sr.read_match()

    if m.host != p.id:
        return

    if new_match.map is not None:
        if new_match.map.map_md5 != m.map.map_md5:
            m.map = new_match.map
            m.mode = Mode(new_match.mode)

            # announce the pp for 100%, 99%, etc. for the chosen map with chosen mods.
            await _handle_command(m.chat, f"!pp [MULTI]", p)

    if new_match.match_name != m.match_name:
        m.match_name = new_match.match_name

    if new_match.freemods != m.freemods:
        if new_match.freemods:
            m.mods = Mods(m.mods & Mods.MULTIPLAYER)
        else:
            for slot in m.slots:
                if slot.mods:
                    slot.mods = Mods.NONE

        m.freemods = new_match.freemods

    if new_match.scoring_type != m.scoring_type:
        m.scoring_type = new_match.scoring_type

    if new_match.team_type != m.team_type:
        m.team_type = new_match.team_type

    m.enqueue_state()


# id: 44
@register_event(BanchoPackets.OSU_MATCH_START)
async def mp_start(p: Player, sr: Reader) -> None:
    if not (m := p.match) or m.in_progress:
        return

    if p.id != m.host:
        log.warn(
            f"{p.username} tried to start the match, while not being the host.")
        return

    for slot in m.slots:
        if slot.status & SlotStatus.OCCUPIED:
            if slot.status != SlotStatus.NOMAP:
                slot.status = SlotStatus.PLAYING
                slot.player.enqueue(writer.match_start(m))

    m.in_progress = True

    m.enqueue_state(lobby=True)


# id: 47
@register_event(BanchoPackets.OSU_MATCH_SCORE_UPDATE)
async def mp_score_update(p: Player, sr: Reader) -> None:
    if not (m := p.match):
        return

    raw_sr = copy.copy(sr)

    raw = raw_sr.read_raw()
    s = sr.read_scoreframe()

    if m.pp_win_condition:
        if os.path.isfile(f".data/beatmaps/{m.map.map_id}.osu"):
            slot = m.find_user(p)
            
            # should not happen
            if not slot:
                return
            
            bmap = BMap(path=f".data/beatmaps/{m.map.map_id}.osu")
            calc = Calculator(
                mode=m.mode,
                n300=s.count_300,
                n100=s.count_100,
                n50=s.count_50,
                n_geki=s.count_geki,
                n_katu=s.count_katu,
                combo=s.max_combo,
                n_misses=s.count_miss,
                mods=slot.mods | m.mods,
            )

            s.score = math.ceil(calc.performance(bmap).pp)  # type: ignore
        else:
            log.fail(f"MATCH {m.match_id}: Couldn't find the osu beatmap.")

    slot_id = m.find_user_slot(p)

    if services.debug:
        log.debug(f"{p.username} has slot id {
                  slot_id} and has incoming score update.")

    m.enqueue(writer.match_score_update(s, slot_id, raw))


# id: 49
@register_event(BanchoPackets.OSU_MATCH_COMPLETE)
async def mp_complete(p: Player, sr: Reader) -> None:
    if not (match := p.match) or not match.in_progress:
        return

    players_played = [slot.player for slot in match.slots if slot.status == SlotStatus.PLAYING]

    for slot in match.slots:
        if slot.player in players_played:
            slot.status = SlotStatus.NOTREADY

    match.in_progress = False

    for slot in match.slots:
        if slot.status & SlotStatus.OCCUPIED and slot.status != SlotStatus.NOMAP:
            slot.status = SlotStatus.NOTREADY
        slot.skipped = False
        slot.loaded = False

    match.enqueue_state(lobby=True)

    for player in players_played:
        player.enqueue(writer.match_complete())

    match.enqueue_state(lobby=True)


# id: 51
@register_event(BanchoPackets.OSU_MATCH_CHANGE_MODS)
async def mp_change_mods(p: Player, sr: Reader) -> None:
    mods = Mods(sr.read_int32())

    if not (match := p.match) or match.in_progress:
        return

    if match.freemods:
        if match.host == p.id:
            match.mods = Mods(mods & Mods.MULTIPLAYER)

            for slot in match.slots:
                if slot.status == SlotStatus.READY:
                    slot.status = SlotStatus.NOTREADY

        slot = match.find_user(p)

        slot.mods = Mods(mods & ~Mods.MULTIPLAYER)
    else:
        if match.host != p.id:
            return

        match.mods = Mods(mods)

        for slot in match.slots:
            if slot.status & SlotStatus.OCCUPIED and slot.status != SlotStatus.NOMAP:
                slot.status = SlotStatus.NOTREADY
    match.enqueue_state()


# id: 52
@register_event(BanchoPackets.OSU_MATCH_LOAD_COMPLETE)
async def mp_load_complete(p: Player, sr: Reader) -> None:
    if not (match := p.match) or not match.in_progress:
        return

    match.find_user(p).loaded = True

    if all(s.loaded for s in match.slots if s.status == SlotStatus.PLAYING):
        match.enqueue(writer.match_all_ready())


# id: 54
@register_event(BanchoPackets.OSU_MATCH_NO_BEATMAP)
async def mp_no_beatmap(p: Player, sr: Reader) -> None:
    if not (match := p.match):
        return

    match.find_user(p).status = SlotStatus.NOMAP

    match.enqueue_state()


# id: 55
@register_event(BanchoPackets.OSU_MATCH_NOT_READY)
async def mp_unready(p: Player, sr: Reader) -> None:
    if not (match := p.match):
        return

    slot = match.find_user(p)

    if slot.status == SlotStatus.NOTREADY:
        return

    slot.status = SlotStatus.NOTREADY

    match.enqueue_state()


# id: 56
@register_event(BanchoPackets.OSU_MATCH_FAILED)
async def match_failed(p: Player, sr: Reader) -> None:
    if not (match := p.match) or not match.in_progress:
        return

    for slot in match.slots:
        if slot.player is not None:
            slot.player.enqueue(writer.match_player_failed(p.id))


# id: 59
@register_event(BanchoPackets.OSU_MATCH_HAS_BEATMAP)
async def has_beatmap(p: Player, sr: Reader) -> None:
    if not (match := p.match):
        return

    match.find_user(p).status = SlotStatus.NOTREADY

    match.enqueue_state()


# id: 60
@register_event(BanchoPackets.OSU_MATCH_SKIP_REQUEST)
async def skip_request(p: Player, sr: Reader) -> None:
    if not (match := p.match) or not match.in_progress:
        return

    slot = match.find_user(p)

    if slot.skipped:
        return

    slot.skipped = True
    match.enqueue(writer.match_player_skipped(p.id))

    for slot in match.slots:
        if slot.status == SlotStatus.PLAYING and not slot.skipped:
            return

    match.enqueue(writer.match_skip())


# id: 63
@register_event(BanchoPackets.OSU_CHANNEL_JOIN, restricted=True)
async def join_channel(p: Player, sr: Reader) -> None:
    _chan = sr.read_str()
    channel = services.channels.get(_chan)
    
    if not channel:
        p.shout(f"{_chan} couldn't be found.")
        return

    channel.connect(p)


# id: 70
@register_event(BanchoPackets.OSU_MATCH_TRANSFER_HOST)
async def mp_transfer_host(p: Player, sr: Reader) -> None:
    if not (match := p.match):
        return

    slot_id = sr.read_int32()

    if not (slot := match.find_slot(slot_id)):
        return

    match.host = slot.player.id
    slot.player.enqueue(writer.match_transfer_host())

    match.enqueue(writer.notification(f"{slot.player.username} became host!"))
    match.enqueue_state()


# id: 73 and 74
@register_event(BanchoPackets.OSU_FRIEND_REMOVE, restricted=True)
async def remove_friend(p: Player, sr: Reader) -> None:
    await p.handle_friend(sr.read_int32())


@register_event(BanchoPackets.OSU_FRIEND_ADD, restricted=True)
async def add_friend(p: Player, sr: Reader) -> None:
    await p.handle_friend(sr.read_int32())


# id: 77
@register_event(BanchoPackets.OSU_MATCH_CHANGE_TEAM)
async def mp_change_team(p: Player, sr: Reader) -> None:
    if not (match := p.match) or match.in_progress:
        return

    slot = match.find_user(p)

    if slot.team == SlotTeams.BLUE:
        slot.team = SlotTeams.RED
    else:
        slot.team = SlotTeams.BLUE

    # Should this really be for every occupied slot? or just the user changing team?
    for slot in match.slots:
        if slot.status & SlotStatus.OCCUPIED and slot.status != SlotStatus.NOMAP:
            slot.status = SlotStatus.NOTREADY

    match.enqueue_state()


# id: 78
@register_event(BanchoPackets.OSU_CHANNEL_PART, restricted=True)
async def part_channel(p: Player, sr: Reader) -> None:
    _chan = sr.read_str()

    if _chan[0] != "#":
        return

    if not (chan := services.channels.get(_chan)):
        log.warn(f"{p.username} tried to part from {
                 _chan}, but channel doesn't exist.")
        return

    chan.disconnect(p)


# id: 85
@register_event(BanchoPackets.OSU_USER_STATS_REQUEST, restricted=True)
async def request_stats(p: Player, sr: Reader) -> None:
    # people id's that current online rn
    user_ids = sr.read_i32_list()

    if len(user_ids) > 32:
        return

    for user_id in user_ids:
        if user_id == p.id:
            continue

        if not (target := services.players.get(user_id)):
            continue

        target.enqueue(writer.update_stats(target))


# id: 87
@register_event(BanchoPackets.OSU_MATCH_INVITE)
async def mp_invite(p: Player, sr: Reader) -> None:
    if not (m := p.match):
        return

    _reciever = sr.read_int32()

    if not (target := services.players.get(_reciever)):
        p.shout("You can't invite someone who's offline.")
        return

    p.send_message(
        f"Come join my multiplayer match: [osump://{m.match_id}/{
            m.match_pass.replace(' ', '_')} {m.match_name}]",
        reciever=target,
    )


# id: 90
@register_event(BanchoPackets.OSU_MATCH_CHANGE_PASSWORD)
async def change_pass(p: Player, sr: Reader) -> None:
    if not (m := p.match) or m.in_progress:
        return

    new_data = await sr.read_match()

    if m.match_pass == new_data.match_pass:
        return

    m.match_pass = new_data.match_pass

    for slot in m.slots:
        if slot.status & SlotStatus.OCCUPIED:
            slot.player.enqueue(writer.match_change_password(new_data.match_pass))

    m.enqueue_state(lobby=True)


# id: 97
@register_event(BanchoPackets.OSU_USER_PRESENCE_REQUEST, restricted=True)
async def request_presence(p: Player, sr: Reader) -> None:
    # people id's that current online rn
    user_ids = sr.read_i32_list()

    if len(user_ids) > 256:
        return

    for user_id in user_ids:
        if user_id == p.id:
            continue

        if not (target := services.players.get(user_id)):
            continue

        if target.bot:
            p.enqueue(writer.bot_presence())
        else:
            p.enqueue(writer.user_presence(target))


# id: 98
@register_event(BanchoPackets.OSU_USER_PRESENCE_REQUEST_ALL, restricted=True)
async def request_presence_all(p: Player, sr: Reader) -> None:
    sr.read_int32()

    for player in services.players:
        player.enqueue(writer.user_presence(player))

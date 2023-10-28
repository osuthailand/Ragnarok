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
IGNORED_PACKETS = 79


@bancho.route("/", methods=["POST", "GET"])
async def handle_bancho(req: Request) -> Response:
    if req.method == "GET":
        msg = services.title_card
        online_players = len(services.players)
        msg += f"\ncurrently {online_players} players online"

        return Response(content=msg.encode())

    if not "user-agent" in req.headers.keys() or req.headers["user-agent"] != "osu!":
        return "no"

    if not "osu-token" in req.headers:
        return await login(req)

    token = req.headers["osu-token"]

    if not (player := services.players.get(token)):
        return Response(
            content=await writer.Notification("Server has restarted")
            + await writer.ServerRestart()
        )

    try:
        body = await req.body()
    except ClientDisconnect:
        log.info(f"{player.username} logged out.")
        await player.logout()
        return Response(content=player.dequeue())

    for p in (sr := Reader(body)):
        if player.is_restricted and (not p.restricted):
            continue

        start = time.time_ns()

        await p.callback(player, sr)

        end = (time.time_ns() - start) / 1e6

        if services.debug and p.packet.value not in IGNORED_PACKETS:
            log.debug(
                f"Packet(id={p.packet.value}, name={p.packet.name}) has been requested by {player.username} - {end:.2f}ms"
            )

    player.last_update = time.time()

    return Response(content=player.dequeue())


ALREADY_ONLINE = "You're already online!"
RESTRICTED_MSG = "Your account has been set in restricted mode."


async def failed_login(code: int, /, extra: bytes = b"") -> Response:
    return Response(
        content=await writer.UserID(code) + extra, headers={"cho-token": "no"}
    )


async def login(req: Request) -> Response:
    data = bytearray(await writer.ProtocolVersion(19))
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

    # get all user needed information
    if not (
        user_info := await services.sql.fetch(
            "SELECT username, id, privileges, "
            "passhash, lon, lat, country FROM users "
            "WHERE safe_username = %s",
            [login_info[0].lower().replace(" ", "_")],
        )
    ):
        return await failed_login(-1)

    # encode user password and input password.
    phash = user_info["passhash"].encode("utf-8")
    pmd5 = login_info[1].encode("utf-8")

    # check if the password is correct
    if phash in services.bcrypt_cache:
        if pmd5 != services.bcrypt_cache[phash]:
            log.warn(
                f"USER {user_info['username']} ({
                    user_info['id']}) | Login fail. (WRONG PASSWORD)"
            )

            return await failed_login(-1)
        else:
            if not bcrypt.checkpw(pmd5, phash):
                log.warn(
                    f"USER {user_info['username']} ({
                        user_info['id']}) | Login fail. (WRONG PASSWORD)"
                )

                return await failed_login(-1)

            services.bcrypt_cache[phash] = pmd5

    if _p := services.players.get(user_info["username"]):
        # user is already online? sus
        log.warn(
            f"A user tried to login onto the account {
                _p.username} ({_p.id}), but user already online."
        )
        return await failed_login(-1, extra=await writer.Notification(ALREADY_ONLINE))

    # invalid security hash (old ver probably using that)
    if len(client_info[3].split(":")) < 4:
        return await failed_login(-1)

    # check if user is restricted; pretty sure its like this lol
    if not user_info["privileges"] & Privileges.VERIFIED | Privileges.PENDING:
        data += await writer.Notification(RESTRICTED_MSG)

    # only allow 2023 clients
    if not client_info[0].startswith("b2023"):
        return await writer.UserID(-2)

    # check if the user is banned.
    if user_info["privileges"] & Privileges.BANNED:
        log.info(
            f"{user_info['username']
               } tried to login, but failed to do so, since they're banned."
        )

        return await failed_login(-3)

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
        *[p.get_friends(), p.update_stats_cache(), p.get_achievements()]
    )

    if not p.is_verified:
        await services.bot.send_message(
            "Since we're still in beta, you'll need to verify your account with a beta key given by one of the founders. "
            "You'll have 30 minutes to verify the account, or the account will be deleted. "
            "To verify your account, please enter !verify <your beta key>",
            reciever=p,
        )

    if not (user_info["lon"] or user_info["lat"]) or user_info["country"] == "XX":
        await p.set_location()
        await p.save_location()

    asyncio.create_task(p.check_loc())

    data += await writer.UserID(p.id)
    data += await writer.UserPriv(p.privileges)

    if services.osu_settings["osu_menu_icon"]["boolean_value"]:
        data += await writer.MainMenuIcon(
            image_url=services.osu_settings["osu_menu_icon"]["string_value"],
            url=f"https://{services.domain}",
        )

    data += await writer.FriendsList(*p.friends)
    data += await writer.UserPresence(p, spoof=True)
    data += await writer.UpdateStats(p)

    for chan in services.channels:
        if chan.public:
            data += await writer.ChanInfo(chan.name)

            if chan.auto_join:
                data += await writer.ChanAutoJoin(chan.name)
                await p.join_channel(chan)

        if chan.staff and p.is_staff:
            data += await writer.ChanInfo(chan.name)
            data += await writer.ChanJoin(chan.name)
            await p.join_channel(chan)

    for player in services.players:
        # NOTE: current player don't need this
        #       because it has been sent already
        if player == p:
            continue

        player.enqueue(await writer.UserPresence(p) + await writer.UpdateStats(p))

        if player.bot:
            data += await writer.BotPresence()
        else:
            data += await writer.UserPresence(player)

        data += await writer.UpdateStats(player)

    data += await writer.ChanInfoEnd()

    et = (time.time_ns() - start) / 1e6

    if services.osu_settings["welcome_message"]["boolean_value"]:
        # maybe add formatting to message?
        data += await writer.Notification(
            services.osu_settings["welcome_message"]["string_value"]
        )

    data += await writer.Notification(f"Authorization took {et:.2f} ms.")

    log.info(f"{p!r} logged in.")

    return Response(content=bytes(data), headers={"cho-token": p.token})


# id: 0
@register_event(BanchoPackets.OSU_CHANGE_ACTION, restricted=True)
async def change_action(p: Player, sr: Reader) -> None:
    p.status = bStatus(sr.read_byte())
    p.status_text = sr.read_str()
    p.beatmap_md5 = sr.read_str()
    p.current_mods = Mods(sr.read_uint32())
    p.play_mode = Mode(sr.read_byte())
    p.beatmap_id = sr.read_int32()

    p.gamemode = (
        Gamemode.RELAX if p.current_mods & Mods.RELAX else
        Gamemode.AUTOPILOT if p.current_mods & Mods.AUTOPILOT else
        Gamemode.VANILLA
    )

    asyncio.create_task(p.update_stats_cache())

    if not p.is_restricted:
        services.players.enqueue(await writer.UpdateStats(p))


async def _handle_command(chan: Channel, msg: str, p: Player):
    if resp := await cmd.handle_commands(message=msg, sender=p, reciever=chan):
        await chan.send(resp, sender=services.bot)


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
        if not (m := p.match):
            return

        chan = m.chat
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
        await p.shout(
            f"You can't send messages to a channel ({
                chan_name}), you're not already connected to."
        )
        return

    await chan.send(msg, p)

    if np := services.regex["np"].search(msg):
        log.info(np.groups())
        p.last_np = await Beatmap._get_beatmap_from_sql("", np.groups(0), 0)
        asyncio.create_task(_handle_command(chan, "!pp ", p))

    if p.token in services.await_response and not services.await_response[p.token]:
        services.await_response[p.token] = msg

    if msg[0] == services.prefix:
        asyncio.create_task(_handle_command(chan, msg, p))


# id: 2
@register_event(BanchoPackets.OSU_LOGOUT, restricted=True)
async def logout(p: Player, sr: Reader) -> None:
    _ = sr.read_int32()

    if (time.time() - p.login_time) < 1:
        return

    log.info(f"{p.username} logged out.")

    await p.logout()


# id: 3
@register_event(BanchoPackets.OSU_REQUEST_STATUS_UPDATE, restricted=True)
async def update_stats(p: Player, sr: Reader) -> None:
    # TODO: add this update for spectator as well
    #       since they need to have up-to-date beatmap info
    p.enqueue(await writer.UpdateStats(p))


# id: 4
@register_event(BanchoPackets.OSU_PING, restricted=True)
async def pong(p: Player, sr: Reader) -> None:
    p.enqueue(await writer.Pong())


# id: 16
@register_event(BanchoPackets.OSU_START_SPECTATING)
async def start_spectate(p: Player, sr: Reader) -> None:
    spec = sr.read_int32()
    host = services.players.get(spec)

    if not p.is_verified or not host:
        return

    await host.add_spectator(p)


# id: 17
@register_event(BanchoPackets.OSU_STOP_SPECTATING)
async def stop_spectate(p: Player, sr: Reader) -> None:
    host = p.spectating

    if not host:
        return

    await host.remove_spectator(p)


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
    ret = await writer.UsrCantSpec(p.id)

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
        await p.shout("The player you're trying to reach is currently offline.")
        return

    if not reciever.bot:
        await p.send_message(msg, reciever=reciever)
    else:
        if np := services.regex["np"].search(msg):
            p.last_np = await Beatmap.get_beatmap(beatmap_id=np.groups(1)[0])

        if msg[0] == services.prefix:
            if resp := await cmd.handle_commands(
                message=msg, sender=p, reciever=services.bot
            ):
                await services.bot.send_message(resp, reciever=p)
                return

        await services.bot.send_message("beep boop", reciever=p)


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
        await p.leave_match()

    for match in services.matches:
        if match.connected:
            p.enqueue(await writer.Match(match))


# id: 31
@register_event(BanchoPackets.OSU_CREATE_MATCH)
async def mp_create_match(p: Player, sr: Reader) -> None:
    m = await sr.read_match()

    services.matches.add(m)

    await p.join_match(m, pwd=m.match_pass)


# id: 32
@register_event(BanchoPackets.OSU_JOIN_MATCH)
async def mp_join(p: Player, sr: Reader) -> None:
    matchid = sr.read_int32()
    matchpass = sr.read_str()

    if p.match or not (m := services.matches.get(matchid)):
        p.enqueue(await writer.MatchFail())
        return

    await p.join_match(m, pwd=matchpass)


# id: 33
@register_event(BanchoPackets.OSU_PART_MATCH)
async def mp_leave(p: Player, sr: Reader) -> None:
    if p.match:
        await p.leave_match()


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

    await m.enqueue_state()


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

    await m.enqueue_state()


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

    await m.enqueue_state()


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

    await m.enqueue_state()


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
                slot.p.enqueue(await writer.MatchStart(m))

    m.in_progress = True

    await m.enqueue_state(lobby=True)


# id: 47
@register_event(BanchoPackets.OSU_MATCH_SCORE_UPDATE)
async def mp_score_update(p: Player, sr: Reader) -> None:
    if not (m := p.match):
        return

    raw_sr = copy.copy(sr)

    raw = raw_sr.read_raw()
    s = sr.read_scoreframe()

    if m.mods & Mods.RELAX or (
        m.pp_win_condition and m.scoring_type == ScoringType.SCORE
    ):
        if os.path.isfile(f".data/beatmaps/{m.map.map_id}.osu"):
            bmap = BMap(path=f".data/beatmaps/{m.map.map_id}.osu")
            log.debug(
                f"{s.count_300=}x300 "
                f"{s.count_100=}x100 "
                f"{s.count_50=}x50 "
                f"{s.count_miss=}m "
                f"{s.max_combo=}x "
            )

            calc = Calculator(
                mode=m.mode,
                n300=s.count_300,
                n100=s.count_100,
                n50=s.count_50,
                n_geki=s.count_geki,
                n_katu=s.count_katu,
                combo=s.max_combo,
                n_misses=s.count_miss,
                mods=m.mods,
            )

            s.score = math.ceil(calc.performance(bmap).pp)  # type: ignore
        else:
            log.fail(f"MATCH {m.match_id}: Couldn't find the osu beatmap.")

    slot_id = m.find_user_slot(p)

    if services.debug:
        log.debug(f"{p.username} has slot id {
                  slot_id} and has incoming score update.")

    m.enqueue(await writer.MatchScoreUpdate(s, slot_id, raw))


# id: 49
@register_event(BanchoPackets.OSU_MATCH_COMPLETE)
async def mp_complete(p: Player, sr: Reader) -> None:
    if not (m := p.match) or not m.in_progress:
        return

    played = [slot.p for slot in m.slots if slot.status == SlotStatus.PLAYING]

    for slot in m.slots:
        if slot.p in played:
            slot.status = SlotStatus.NOTREADY

    m.in_progress = False

    for slot in m.slots:
        if slot.status & SlotStatus.OCCUPIED and slot.status != SlotStatus.NOMAP:
            slot.status = SlotStatus.NOTREADY
        slot.skipped = False
        slot.loaded = False

    await m.enqueue_state(lobby=True)

    for pl in played:
        pl.enqueue(await writer.MatchComplete())

    await m.enqueue_state(lobby=True)


# id: 51
@register_event(BanchoPackets.OSU_MATCH_CHANGE_MODS)
async def mp_change_mods(p: Player, sr: Reader) -> None:
    mods = sr.read_int32()

    if not (m := p.match) or m.in_progress:
        return

    if m.freemods:
        if m.host == p.id:
            if mods & Mods.MULTIPLAYER:
                m.mods = Mods(mods & Mods.MULTIPLAYER)

                for slot in m.slots:
                    if slot.status == SlotStatus.READY:
                        slot.status = SlotStatus.NOTREADY

        slot = m.find_user(p)

        slot.mods = Mods(mods - (mods & Mods.MULTIPLAYER))
    else:
        if m.host != p.id:
            return

        m.mods = Mods(mods)

        for slot in m.slots:
            if slot.status & SlotStatus.OCCUPIED and slot.status != SlotStatus.NOMAP:
                slot.status = SlotStatus.NOTREADY

    await m.enqueue_state()


# id: 52
@register_event(BanchoPackets.OSU_MATCH_LOAD_COMPLETE)
async def mp_load_complete(p: Player, sr: Reader) -> None:
    if not (m := p.match) or not m.in_progress:
        return

    m.find_user(p).loaded = True

    if all(s.loaded for s in m.slots if s.status == SlotStatus.PLAYING):
        m.enqueue(await writer.MatchAllReady())


# id: 54
@register_event(BanchoPackets.OSU_MATCH_NO_BEATMAP)
async def mp_no_beatmap(p: Player, sr: Reader) -> None:
    if not (m := p.match):
        return

    m.find_user(p).status = SlotStatus.NOMAP

    await m.enqueue_state()


# id: 55
@register_event(BanchoPackets.OSU_MATCH_NOT_READY)
async def mp_unready(p: Player, sr: Reader) -> None:
    if not (m := p.match):
        return

    slot = m.find_user(p)

    if slot.status == SlotStatus.NOTREADY:
        return

    slot.status = SlotStatus.NOTREADY

    await m.enqueue_state()


# id: 56
@register_event(BanchoPackets.OSU_MATCH_FAILED)
async def match_failed(p: Player, sr: Reader) -> None:
    if not (m := p.match) or not m.in_progress:
        return

    for slot in m.slots:
        if slot.p is not None:
            slot.p.enqueue(await writer.MatchPlayerFailed(p.id))


# id: 59
@register_event(BanchoPackets.OSU_MATCH_HAS_BEATMAP)
async def has_beatmap(p: Player, sr: Reader) -> None:
    if not (m := p.match):
        return

    m.find_user(p).status = SlotStatus.NOTREADY

    await m.enqueue_state()


# id: 60
@register_event(BanchoPackets.OSU_MATCH_SKIP_REQUEST)
async def skip_request(p: Player, sr: Reader) -> None:
    if not (m := p.match) or not m.in_progress:
        return

    slot = m.find_user(p)

    if slot.skipped:
        return

    slot.skipped = True
    m.enqueue(await writer.MatchPlayerReqSkip(p.id))

    for slot in m.slots:
        if slot.status == SlotStatus.PLAYING and not slot.skipped:
            return

    m.enqueue(await writer.MatchSkip())


# id: 63
@register_event(BanchoPackets.OSU_CHANNEL_JOIN, restricted=True)
async def join_osu_channel(p: Player, sr: Reader) -> None:
    channel = sr.read_str()

    # if channel == "#spectator":
    #     if p.spectating:
    #         channel = f"#spect_{p.spectating.id}"
    #     elif p.spectators:
    #         channel = f"#spect_{p.id}"
    #     else:
    #         log.debug(f"{channel} error jefoiwejfoeiw")
    #         return

    # if channel == "#multiplayer":
    #     if not p.match:
    #         return

    #     channel = p.match.chat._name

    if not (c := services.channels.get(channel)):
        log.fail(f"{p.username} tried to join channel {
                 channel}, but failed so.")
        await p.shout(f"Channel ({channel}) couldn't be found.")
        return

    await p.join_channel(c)


# id: 70
@register_event(BanchoPackets.OSU_MATCH_TRANSFER_HOST)
async def mp_transfer_host(p: Player, sr: Reader) -> None:
    if not (m := p.match):
        return

    slot_id = sr.read_int32()

    if not (slot := m.find_slot(slot_id)):
        return

    m.host = slot.p.id
    slot.p.enqueue(await writer.MatchTransferHost())

    m.enqueue(await writer.Notification(f"{slot.p.username} became host!"))
    await m.enqueue_state()


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
    if not (m := p.match) or m.in_progress:
        return

    slot = m.find_user(p)

    if slot.team == SlotTeams.BLUE:
        slot.team = SlotTeams.RED
    else:
        slot.team = SlotTeams.BLUE

    # Should this really be for every occupied slot? or just the user changing team?
    for slot in m.slots:
        if slot.status & SlotStatus.OCCUPIED and slot.status != SlotStatus.NOMAP:
            slot.status = SlotStatus.NOTREADY

    await m.enqueue_state()


# id: 78
@register_event(BanchoPackets.OSU_CHANNEL_PART, restricted=True)
async def leave_osu_channel(p: Player, sr: Reader) -> None:
    _chan = sr.read_str()

    # if _chan == "#spectator":
    #     if p.spectating:
    #         _chan = f"#spect_{p.spectating.id}"
    #     elif p.spectators:
    #         _chan = f"#spect_{p.id}"
    #     else:
    #         return

    # if _chan == "#multiplayer":
    #     if not p.match:
    #         return

    #     _chan = p.match.chat._name

    if not (chan := services.channels.get(_chan)):
        log.warn(f"{p.username} tried to part from {
                 _chan}, but channel doesn't exist.")
        return

    if not chan.is_dm:
        await p.leave_channel(chan)


# id: 85
@register_event(BanchoPackets.OSU_USER_STATS_REQUEST, restricted=True)
async def request_stats(p: Player, sr: Reader) -> None:
    # people id's that current online rn
    users = sr.read_i32_list()

    if len(users) > 32:
        return

    for user in users:
        if user == p.id:
            continue

        if not (u := services.players.get(user)):
            continue

        u.enqueue(await writer.UpdateStats(u))


# id: 87
@register_event(BanchoPackets.OSU_MATCH_INVITE)
async def mp_invite(p: Player, sr: Reader) -> None:
    if not (m := p.match):
        return

    _reciever = sr.read_int32()

    if not (reciever := services.players.get(_reciever)):
        await p.shout("You can't invite someone who's offline.")
        return

    await p.send_message(
        f"Come join my multiplayer match: [osump://{m.match_id}/{
            m.match_pass.replace(' ', '_')} {m.match_name}]",
        reciever=reciever,
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
            slot.p.enqueue(await writer.MatchPassChange(new_data.match_pass))

    await m.enqueue_state(lobby=True)


# id: 97
@register_event(BanchoPackets.OSU_USER_PRESENCE_REQUEST, restricted=True)
async def request_presence(p: Player, sr: Reader) -> None:
    # people id's that current online rn
    users = sr.read_i32_list()

    if len(users) > 256:
        return

    for user in users:
        if user == p.id:
            continue

        if not (u := services.players.get(user)):
            continue

        if u.bot:
            p.enqueue(await writer.UserPresence(u))
        else:
            p.enqueue(await writer.UserPresence(u))


# id: 98
@register_event(BanchoPackets.OSU_USER_PRESENCE_REQUEST_ALL, restricted=True)
async def request_presence_all(p: Player, sr: Reader) -> None:
    sr.read_int32()

    for player in services.players:
        player.enqueue(await writer.UserPresence(player))

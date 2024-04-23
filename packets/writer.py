from constants.player import Ranks, Privileges
from constants.packets import BanchoPackets
from constants.match import SlotStatus
from typing import Any, TYPE_CHECKING
from enum import unique, IntEnum
from objects import services
import struct
import math


if TYPE_CHECKING:
    from objects.channel import Channel
    from objects.match import Match
    from objects.player import Player
    from objects.score import ScoreFrame

spec = ("<b", "<B", "<h", "<H", "<i", "<I", "<f", "<q", "<Q", "<d")


@unique
class Types(IntEnum):
    int8 = 0
    uint8 = 1
    int16 = 2
    uint16 = 3
    int32 = 4
    uint32 = 5
    float32 = 6
    int64 = 7
    uint64 = 8
    float64 = 9

    match = 13

    byte = 100
    ubyte = 110

    int32_list = 10
    string = 19
    raw = 20

    multislots = 21
    multislotsmods = 22

    message = 23


def write_uleb128(value: int) -> bytearray:
    if value == 0:
        return bytearray(b"\x00")

    data: bytearray = bytearray()
    length: int = 0

    while value > 0:
        data.append(value & 0x7F)
        value >>= 7
        if value != 0:
            data[length] |= 0x80

        length += 1

    return data


def write_byte(value: int) -> bytearray:
    return bytearray(struct.pack("<b", value))


def write_ubyte(value: int) -> bytearray:
    return struct.pack("<B", value)


def write_int32(value: int) -> bytearray:
    return struct.pack("<i", value)


def write_int32_list(values: tuple[int]) -> bytearray:
    data = bytearray(len(values).to_bytes(2, "little"))

    for value in values:
        data += value.to_bytes(4, "little")

    return data


def write_multislots(slots) -> bytearray:
    ret = bytearray()

    ret.extend([s.status for s in slots])
    ret.extend([s.team for s in slots])

    for slot in slots:
        if slot.status & SlotStatus.OCCUPIED:
            ret += slot.player.id.to_bytes(4, "little")

    return ret


def write_multislotsmods(slots) -> bytearray:
    ret = bytearray()

    for slot in slots:
        ret += slot.mods.to_bytes(4, "little")

    return ret


def write_str(string: str) -> bytearray:
    if not string:
        return bytearray(b"\x00")

    data = bytearray(b"\x0B")

    data += write_uleb128(len(string.encode()))
    data += string.encode()
    return data


def write_msg(sender: str, msg: str, chan: str, id: int) -> bytearray:
    ret = bytearray()

    ret += write_str(sender)
    ret += write_str(msg)
    ret += write_str(chan)
    ret += id.to_bytes(4, "little", signed=True)

    return ret


def write(pID: int, *args: tuple[Any, ...]) -> bytes:
    data = bytearray(struct.pack("<Hx", pID))

    for args, d_type in args:
        if d_type == Types.string:
            data += write_str(args)
        elif d_type == Types.raw:
            data += args
        elif d_type == Types.int32:
            data += write_int32(args)
        elif d_type == Types.int32_list:
            data += write_int32_list(args)
        elif d_type == Types.multislots:
            data += write_multislots(args)
        elif d_type == Types.multislotsmods:
            data += write_multislotsmods(args)
        elif d_type == Types.byte:
            data += write_byte(args)
        elif d_type == Types.ubyte:
            data += write_ubyte(args)
        elif d_type == Types.message:
            data += write_msg(*args)
        else:
            data += struct.pack(spec[d_type], args)

    data[3:3] += struct.pack("<I", len(data) - 3)
    return bytes(data)


def user_id(user_id: int) -> bytes:
    """
    ID Responses:
    -1: Authentication Failure
    -2: Old Client
    -3: Banned (due to breaking the game rules)
    -4: Banned (due to account deactivation)
    -5: An error occurred
    -6: Needs Supporter
    -7: Password Reset
    -8: Requires Verification
    > -1: Valid ID
    """
    return write(BanchoPackets.CHO_USER_ID, (user_id, Types.int32))


def spectator_joined(user_id: int) -> bytes:
    return write(BanchoPackets.CHO_SPECTATOR_JOINED, (user_id, Types.int32))


def spectator_left(user_id: int) -> bytes:
    return write(BanchoPackets.CHO_SPECTATOR_LEFT, (user_id, Types.int32))


def fellow_spectator_joined(user_id: int) -> bytes:
    return write(BanchoPackets.CHO_FELLOW_SPECTATOR_JOINED, (user_id, Types.int32))


def fellow_spectator_left(user_id: int) -> bytes:
    return write(BanchoPackets.CHO_FELLOW_SPECTATOR_LEFT, (user_id, Types.int32))


def spectator_cant_spectate(user_id: int) -> bytes:
    return write(BanchoPackets.CHO_SPECTATOR_CANT_SPECTATE, (user_id, Types.int32))


def notification(msg: str) -> bytes:
    return write(BanchoPackets.CHO_NOTIFICATION, (msg, Types.string))


def user_privileges(privileges: int) -> bytes:
    rank = Ranks.NONE
    rank |= Ranks.SUPPORTER

    if privileges & Privileges.VERIFIED:
        rank |= Ranks.NORMAL

    if privileges & Privileges.BAT:
        rank |= Ranks.BAT

    if privileges & Privileges.MODERATOR:
        rank |= Ranks.FRIEND

    if privileges & Privileges.ADMIN:
        rank |= Ranks.FRIEND

    if privileges & Privileges.DEV:
        rank |= Ranks.PEPPY

    return write(BanchoPackets.CHO_PRIVILEGES, (rank, Types.int32))


def protocol_version(version: int) -> bytes:
    return write(BanchoPackets.CHO_PROTOCOL_VERSION, (version, Types.int32))


def update_friends(friends_id: tuple[int]):
    return write(BanchoPackets.CHO_FRIENDS_LIST, (friends_id, Types.int32_list))


def update_stats(p: "Player") -> bytes:
    if p not in services.players:
        return b""

    pp_overflow = p.pp > 32767

    return write(
        BanchoPackets.CHO_USER_STATS,
        (p.id, Types.int32),
        (p.status.value, Types.uint8),
        (p.status_text, Types.string),
        (p.beatmap_md5, Types.string),
        (p.current_mods, Types.int32),
        (p.play_mode, Types.uint8),
        (p.beatmap_id, Types.int32),
        (p.ranked_score if not pp_overflow else p.pp, Types.int64),
        (p.accuracy / 100.0, Types.float32),
        (p.playcount, Types.int32),
        (p.total_score, Types.int64),
        (p.rank, Types.int32),
        (math.ceil(p.pp) if not pp_overflow else 0, Types.int16),
    )


def bot_presence() -> bytes:
    p = services.bot

    return write(
        BanchoPackets.CHO_USER_PRESENCE,
        (p.id, Types.int32),
        (p.username, Types.string),
        (p.timezone, Types.byte),
        (1, Types.ubyte),
        (1, Types.byte),
        (1, Types.float32),
        (1, Types.float32),
        (0, Types.int32),
    )


def user_presence(p: "Player", spoof: bool = False) -> bytes:
    if p not in services.players:
        return b""

    rank = Ranks.NONE

    if spoof:
        rank |= Ranks.SUPPORTER

    if p.privileges & Privileges.VERIFIED:
        rank |= Ranks.NORMAL

    if p.privileges & Privileges.BAT:
        rank |= Ranks.BAT

    if p.privileges & Privileges.SUPPORTER:
        rank |= Ranks.SUPPORTER

    if p.privileges & Privileges.MODERATOR:
        rank |= Ranks.FRIEND

    if p.privileges & Privileges.ADMIN:
        rank |= Ranks.FRIEND

    if p.privileges & Privileges.DEV:
        rank |= Ranks.PEPPY

    return write(
        BanchoPackets.CHO_USER_PRESENCE,
        (p.id, Types.int32),
        (p.username, Types.string),
        (p.timezone, Types.byte),
        (p.country_code, Types.ubyte),
        (rank, Types.byte),
        (p.longitude, Types.float32),
        (p.latitude, Types.float32),
        (p.rank, Types.int32),
    )


def channel_join(name: str) -> bytes:
    return write(BanchoPackets.CHO_CHANNEL_JOIN_SUCCESS, (name, Types.string))


def channel_kick(name: str) -> bytes:
    return write(BanchoPackets.CHO_CHANNEL_KICK, (name, Types.string))


def channel_auto_join(name: str) -> bytes:
    return write(BanchoPackets.CHO_CHANNEL_AUTO_JOIN, (name, Types.string))


def channel_info(chan: "Channel") -> bytes:
    return write(
        BanchoPackets.CHO_CHANNEL_INFO,
        (chan.display_name, Types.string),
        (chan.description, Types.string),
        (len(chan.connected), Types.int32),
    )


def channel_info_end() -> bytes:
    return write(BanchoPackets.CHO_CHANNEL_INFO_END)


def server_restart() -> bytes:
    return write(BanchoPackets.CHO_RESTART, (0, Types.int32))


def send_message(sender: str, message: str, channel: str, id: int) -> bytes:
    return write(
        BanchoPackets.CHO_SEND_MESSAGE,
        ((sender, message, channel, id), Types.message),
    )


def logout(id: int) -> bytes:
    return write(
        BanchoPackets.CHO_USER_LOGOUT,
        (id, Types.int32),
        (0, Types.uint8),
    )


def friends_list(ids: set[int]) -> bytes:
    return write(BanchoPackets.CHO_FRIENDS_LIST, (ids, Types.int32_list))


def get_match_struct(m: "Match", send_pass: bool = False) -> bytes:
    struct = [
        (m.match_id, Types.int16),
        (m.in_progress, Types.int8),
        (0, Types.byte),
        (m.mods, Types.uint32),
        (m.match_name, Types.string),
    ]

    if m.match_pass:
        if send_pass:
            struct.append((m.match_pass, Types.string))
        else:
            struct.append(("trollface", Types.string))
    else:
        struct.append(("", Types.string))

    struct.extend(
        (
            (m.map.title, Types.string),
            (m.map.map_id, Types.int32),
            (m.map.map_md5, Types.string),
            (m.slots, Types.multislots),
            (m.host, Types.int32),
            (m.mode.value, Types.byte),
            (m.scoring_type.value, Types.byte),
            (m.team_type.value, Types.byte),
            (m.freemods, Types.byte),
        )
    )

    if m.freemods:
        struct.append((m.slots, Types.multislotsmods))

    struct.append((m.seed, Types.int32))

    return struct


def match(m: "Match") -> bytes:
    struct = get_match_struct(m)
    return write(BanchoPackets.CHO_NEW_MATCH, *struct)


def match_all_ready() -> bytes:
    return write(BanchoPackets.CHO_MATCH_ALL_PLAYERS_LOADED)


def match_complete():
    return write(BanchoPackets.CHO_MATCH_COMPLETE)


def match_dispose(mid: int) -> bytes:
    return write(BanchoPackets.CHO_DISPOSE_MATCH, (mid, Types.int32))


def match_fail() -> bytes:
    return write(BanchoPackets.CHO_MATCH_JOIN_FAIL)


def match_invite(m: "Match", p: "Player", reciever) -> bytes:
    return write(
        BanchoPackets.CHO_MATCH_INVITE,
        ((p.username, f"#multi_{m.match_id}", reciever, p.id), Types.message),
    )


def match_join(m: "Match") -> bytes:
    struct = get_match_struct(m, send_pass=True)
    return write(BanchoPackets.CHO_MATCH_JOIN_SUCCESS, *struct)


def match_change_password(pwd: str) -> bytes:
    return write(BanchoPackets.CHO_MATCH_CHANGE_PASSWORD, (pwd, Types.string))


def match_player_failed(pid: int) -> bytes:
    return write(BanchoPackets.CHO_MATCH_PLAYER_FAILED, (pid, Types.int32))


def match_score_update(s: "ScoreFrame", slot_id: int, raw_data: bytes) -> bytes:
    ret = bytearray(b"0\x00\x00")

    ret += len(raw_data).to_bytes(4, "little")

    ret += s.time.to_bytes(4, "little", signed="True")
    ret += struct.pack("<b", slot_id)

    ret += struct.pack(
        "<HHHHHH",
        s.count_300,
        s.count_100,
        s.count_50,
        s.count_geki,
        s.count_katu,
        s.count_miss,
    )

    ret += s.score.to_bytes(4, "little", signed=True)

    ret += struct.pack("<HH", s.max_combo, s.combo)

    ret += struct.pack("<bbbb", s.perfect, s.current_hp, s.tag_byte, s.score_v2)

    return ret


def match_player_skipped(user_id: int) -> bytes:
    return write(BanchoPackets.CHO_MATCH_PLAYER_SKIPPED, (user_id, Types.int32))


def match_skip() -> bytes:
    return write(BanchoPackets.CHO_MATCH_SKIP)


def match_start(m: "Match") -> bytes:
    struct = get_match_struct(m, send_pass=True)
    return write(BanchoPackets.CHO_MATCH_START, *struct)


def match_transfer_host() -> bytes:
    return write(BanchoPackets.CHO_MATCH_TRANSFER_HOST)


def match_update(m: "Match") -> bytes:
    struct = get_match_struct(m, send_pass=True)
    return write(BanchoPackets.CHO_UPDATE_MATCH, *struct)


def pong() -> bytes:
    return write(BanchoPackets.CHO_PONG)

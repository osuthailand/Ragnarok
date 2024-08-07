from enum import IntEnum
from typing import Callable, Iterator
from constants.packets import ClientPackets
from objects.score import ScoreFrame
from constants.playmode import Mode
from dataclasses import dataclass
from objects.match import Match
from constants.mods import Mods
from constants.match import *
from objects import services

import struct

IGNORED_PACKETS = [4, 79]


@dataclass
class Packet:
    packet: ClientPackets

    callback: Callable
    restricted: bool


class SpectateAction(IntEnum):
    NORMAL = 0
    NEW_SONG = 1
    SKIP = 2
    COMPLETION = 3
    FAIL = 4
    PAUSE = 5
    RESUME = 6
    SELECTING = 7
    SPECTATING = 8


@dataclass
class SpectateFrame:
    buttons: int
    taiko_u8: int
    x: float
    y: float
    time: int


@dataclass
class SpectateFrameFinished:
    frames: list[SpectateFrame]
    score: ScoreFrame
    action: SpectateAction
    extra: int
    sequence: int

    raw: memoryview


class Reader:
    def __init__(self, packet_data: bytes):
        self.packet_data = memoryview(packet_data)
        self.offset = 0
        self.packet, self.plen = None, 0

    def __iter__(self) -> Iterator[Packet]:
        return self

    def __next__(self) -> Packet:
        while self.data:
            self.packet, self.plen = self.read_headers()

            if self.packet not in services.packets:
                if services.debug and self.packet not in IGNORED_PACKETS:
                    services.logger.warn(
                        f"Packet <{ClientPackets(self.packet)} | {ClientPackets(self.packet).name}> has been requested although it's an unregistered packet."
                    )

                if self.plen != 0:
                    self.offset += self.plen
            else:
                break
        else:
            raise StopIteration

        self.packet = ClientPackets(self.packet)

        return services.packets[self.packet.value]

    def read_headers(self) -> tuple[ClientPackets, int]:
        if len(self.data) < 7:
            raise StopIteration

        ret = struct.unpack("<HxI", self.data[:7])
        self.offset += 7
        return ret[0], ret[1]

    @property
    def data(self):
        return self.packet_data[self.offset :]

    def read_bytes(self, size: int):
        ret = struct.unpack("<" + "B" * size, self.data[:size])
        self.offset += size
        return ret

    def read_byte(self) -> int:
        ret = struct.unpack("<b", self.data[:1])
        self.offset += 1
        return ret[0]

    def read_ubyte(self) -> int:
        ret = struct.unpack("<B", self.data[:1])
        self.offset += 1
        return ret[0]

    def read_int8(self) -> int:
        ret = int.from_bytes(self.data[:1], "little", signed=True)
        self.offset += 1
        return ret - 256 if ret > 127 else ret

    def read_uint8(self) -> int:
        ret = int.from_bytes(self.data[:1], "little", signed=False)
        self.offset += 1
        return ret

    def read_int16(self) -> int:
        ret = int.from_bytes(self.data[:2], "little", signed=True)
        self.offset += 2
        return ret

    def read_uint16(self) -> int:
        ret = int.from_bytes(self.data[:2], "little", signed=False)
        self.offset += 2
        return ret

    def read_int32(self) -> int:
        ret = int.from_bytes(self.data[:4], "little", signed=True)
        self.offset += 4
        return ret

    def read_uint32(self) -> int:
        ret = int.from_bytes(self.data[:4], "little", signed=False)
        self.offset += 4
        return ret

    def read_int64(self) -> int:
        ret = int.from_bytes(self.data[:8], "little", signed=True)
        self.offset += 8
        return ret

    def read_uint64(self) -> int:
        ret = int.from_bytes(self.data[:8], "little", signed=False)
        self.offset += 8
        return ret

    def read_int32_list(self) -> tuple[int]:
        length = self.read_int16()

        ret = struct.unpack(f"<{'I' * length}", self.data[: length * 4])

        self.offset += length * 4
        return ret

    def read_float32(self) -> float:
        ret = struct.unpack("<f", self.data[:4])
        self.offset += 4
        return ret[0]

    def read_float64(self) -> float:
        ret = struct.unpack("<d", self.data[:8])
        self.offset += 8
        return ret[0]

    def read_string(self, dot_net_str: bool = False) -> str:
        if not dot_net_str:
            is_string = self.data[0] == 0x0B
            self.offset += 1

            if not is_string:
                return ""

        result = shift = 0

        while True:
            b = self.data[0]
            self.offset += 1

            result |= (b & 0b01111111) << shift
            if (b & 0b10000000) == 0:
                break

            shift += 7

        ret = self.data[:result].tobytes().decode()

        self.offset += result
        return ret

    def read_raw(self) -> memoryview:
        ret = self.data[: self.plen]
        self.offset += self.plen
        return ret

    async def read_match(self) -> Match:
        match = Match()

        match.id = len(services.matches)

        self.offset += 2

        match.in_progress = self.read_int8() == 1

        self.read_int8()  # ignore match type; 0 = normal osu!, 1 = osu! arcade

        match.mods = Mods(self.read_int32())

        match.name = self.read_string()
        match.password = self.read_string()

        self.read_string()  # map title
        map_id = self.read_int32()
        map_md5 = self.read_string()

        match.map = await services.beatmaps.get(map_md5)

        if not match.map:
            match.map = await services.beatmaps.get_by_map_id(map_id)

        for slot in match.slots:
            slot.status = SlotStatus(self.read_int8())

        for slot in match.slots:
            slot.team = SlotTeams(self.read_int8())

        for slot in match.slots:
            if slot.status.is_occupied:
                self.offset += 4

        match.host = self.read_int32()

        match.mode = Mode(self.read_int8())
        match.scoring_type = ScoringType(self.read_int8())
        match.team_type = TeamType(self.read_int8())

        match.freemods = self.read_int8() == 1

        if match.freemods:
            for slot in match.slots:
                slot.mods = Mods(self.read_int32())

        match.seed = self.read_int32()

        return match

    def read_score_frame(self) -> ScoreFrame:
        score_frame = ScoreFrame()

        score_frame.time = self.read_int32()
        score_frame.id = self.read_byte()

        score_frame.count_300 = self.read_uint16()
        score_frame.count_100 = self.read_uint16()
        score_frame.count_50 = self.read_uint16()
        score_frame.count_geki = self.read_uint16()
        score_frame.count_katu = self.read_uint16()
        score_frame.count_miss = self.read_uint16()

        score_frame.score = self.read_int32()

        score_frame.max_combo = self.read_uint16()
        score_frame.combo = self.read_uint16()

        score_frame.perfect = self.read_int8() == 1

        score_frame.current_hp = self.read_byte()
        score_frame.tag_byte = self.read_byte()

        score_frame.score_v2 = self.read_int8() == 1

        if score_frame.score_v2:
            self.read_float64()
            self.read_float64()

        return score_frame

    def read_spectate_frame(self) -> SpectateFrame:
        return SpectateFrame(
            buttons=self.read_uint8(),
            taiko_u8=self.read_uint8(),
            x=self.read_float32(),
            y=self.read_float32(),
            time=self.read_int32(),
        )

    def read_spectate_packet(self) -> SpectateFrameFinished:
        raw = self.data[: self.offset]
        extra = self.read_int32()
        count = self.read_uint16()
        frames = [self.read_spectate_frame() for _ in range(count)]
        action = SpectateAction(self.read_uint8())
        score = self.read_score_frame()
        sequence = self.read_uint16()

        return SpectateFrameFinished(frames, score, action, extra, sequence, raw)

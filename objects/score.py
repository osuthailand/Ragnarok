import math
import time

from utils import score
from enum import IntEnum
from typing import TYPE_CHECKING, Optional
from base64 import b64decode
from objects import services
from dataclasses import dataclass
from rina_pp_pyb import Performance, Beatmap as BMap

from constants.mods import Mods
from objects.beatmap import Beatmap
from constants.playmode import Gamemode, Mode
from constants.playmode import Mode
from constants.beatmap import Approved
from py3rijndael.rijndael import RijndaelCbc
from py3rijndael.paddings import ZeroPadding
from objects.player import Player


@dataclass
class ScoreFrame:
    time: int = 0
    id: int = 0

    count_300: int = 0
    count_100: int = 0
    count_50: int = 0

    count_geki: int = 0
    count_katu: int = 0
    count_miss: int = 0

    score: int = 0
    max_combo: int = 0
    combo: int = 0

    perfect: bool = False

    current_hp: int = 0
    tag_byte: int = 0

    score_v2: bool = False


class SubmitStatus(IntEnum):
    FAILED = 0
    QUIT = 1
    PASSED = 2
    BEST = 3


class Score:
    def __init__(self):
        self.player: Player = None  # type: ignore
        self.map: Beatmap = None  # type: ignore

        self.id: int = 0

        self.score: int = 0
        self.pp: float = 0.0

        self.count_300: int = 0
        self.count_100: int = 0
        self.count_50: int = 0

        self.count_geki: int = 0
        self.count_katu: int = 0
        self.count_miss: int = 0

        self.total_hits: int = 0
        self.max_combo: int = 0
        self.accuracy: float = 0.0

        self.perfect: bool = False

        self.rank: str = "F"

        self.mods: Mods = Mods.NONE
        self.status: SubmitStatus = SubmitStatus.FAILED

        self.playtime: int = 0

        self.mode: Mode = Mode.OSU

        self.submitted: int = math.ceil(time.time())

        self.gamemode: Gamemode = Gamemode.VANILLA

        self.position: int = 0

        # previous_best
        self.pb: "Score" = None  # type: ignore

        self._awards_pp: bool = False

    @property
    def web_format(self) -> str:
        return (
            f"\n{self.id}|{self.player.username}|{
                self.score if self.gamemode == Gamemode.VANILLA else math.ceil(self.pp)}|"
            f"{self.max_combo}|{self.count_50}|{self.count_100}|{
                self.count_300}|{self.count_miss}|"
            f"{self.count_katu}|{self.count_geki}|{
                self.perfect}|{self.mods}|{self.player.id}|"
            f"{self.position}|{self.submitted}|1"
        )

    @classmethod
    async def set_data_from_sql(cls, data: dict[str, float | int | str]) -> "Score":
        s = cls()

        s.id = data["id"]

        s.score = data["score"]
        s.pp = data["pp"]

        s.count_300 = data["count_300"]
        s.count_100 = data["count_100"]
        s.count_50 = data["count_50"]
        s.count_geki = data["count_geki"]
        s.count_katu = data["count_katu"]
        s.count_miss = data["count_miss"]

        s.total_hits = s.count_300 + s.count_100 + s.count_50

        s.max_combo = data["max_combo"]
        s.accuracy = data["accuracy"]

        s.perfect = data["perfect"]

        s.rank = data["rank"]
        s.mods = Mods(data["mods"])

        s.playtime = data["playtime"]

        s.status = SubmitStatus(data["status"])
        s.mode = Mode(data["mode"])

        s.submitted = data["submitted"]

        s.gamemode = Gamemode(data["gamemode"])

        return s

    @classmethod
    async def set_data_from_submission(
        cls,
        score_enc: bytes,
        iv: bytes,
        key: str,
        exited: int
        # ) -> "Score" | None:
    ) -> Optional["Score"]:
        score_latin = b64decode(score_enc).decode("latin_1")
        iv_latin = b64decode(iv).decode("latin_1")

        data = (
            RijndaelCbc(key, iv_latin, ZeroPadding(32), 32)  # type: ignore
            .decrypt(score_latin)
            .decode()
            .split(":")
        )

        s = cls()

        if not (player := services.players.get(data[1].rstrip())):
            return

        s.player = player

        if not (bmap := await services.beatmaps.get(data[0])):
            return

        s.map = bmap

        s.count_300 = int(data[3])
        s.count_100 = int(data[4])
        s.count_50 = int(data[5])
        s.count_geki = int(data[6])
        s.count_katu = int(data[7])
        s.count_miss = int(data[8]) 
        s.score = int(data[9])
        s.max_combo = int(data[10])

        s.mode = Mode(int(data[15]))

        s.accuracy = score.calculate_accuracy(
            s.mode,
            s.count_300,
            s.count_100,
            s.count_50,
            s.count_geki,
            s.count_katu,
            s.count_miss,
        )

        s.total_hits = s.count_300 + s.count_100 + s.count_50

        s.perfect = s.max_combo == s.map.max_combo

        s.rank = data[12]

        s.mods = Mods(int(data[13]))
        passed = data[14] == "True"

        if exited:
            s.status = SubmitStatus.QUIT

        mods = int(data[13])
        s.gamemode = (
            Gamemode.RELAX
            if mods & Mods.RELAX
            else Gamemode.VANILLA
        )

        if passed:
            await s.calculate_position()

            if s.map.approved & Approved.HAS_LEADERBOARD:
                bmap = BMap(path=f".data/beatmaps/{s.map.file}")

                if s.mode != bmap.mode:
                    bmap.convert(s.mode)

                perf = Performance(
                    n300=s.count_300,
                    n100=s.count_100,
                    n50=s.count_50,
                    misses=s.count_miss,
                    n_geki=s.count_geki,
                    n_katu=s.count_katu,
                    combo=s.max_combo,
                    mods=s.mods
                ).calculate(bmap)

                s.pp = perf.pp

                if math.isnan(s.pp) or math.isinf(s.pp):
                    s.pp = 0

                s.awards_pp = s.map.approved & Approved.AWARDS_PP # type: ignore

            # find our previous best score on the map
            if prev_best := await services.sql.fetch(
                "SELECT id, user_id, map_md5, score, pp, count_300, count_100, "
                "count_50, count_geki, count_katu, count_miss, "
                "max_combo, accuracy, perfect, rank, mods, status, "
                "playtime, mode, submitted, gamemode FROM scores "
                "WHERE user_id = %s AND gamemode = %s AND map_md5 = %s "
                "AND mode = %s AND status = 3 LIMIT 1",
                (s.player.id, s.gamemode, s.map.map_md5, s.mode.value),
            ):
                s.pb = await Score.set_data_from_sql(prev_best)

                # identical to `calculate_position(self)`
                position = await services.sql.fetch(
                    "SELECT COUNT(*) AS rank FROM scores s "
                    "INNER JOIN beatmaps b ON b.map_md5 = s.map_md5 "
                    "INNER JOIN users u ON u.id = s.user_id "
                    "WHERE s.score > %s AND s.gamemode = %s "
                    "AND b.map_md5 = %s AND u.privileges & 4 "
                    "AND s.status = 3 AND s.mode = %s "
                    "ORDER BY s.score DESC, s.submitted DESC",
                    (s.pb.score, s.pb.gamemode, s.map.map_md5, s.pb.mode.value),
                )
                s.pb.position = position["rank"] + 1

                # if we found a personal best score
                # that has more score on the map,
                # we set it to passed.
                if (
                    s.pb.pp < s.pp
                    if s.gamemode != Gamemode.VANILLA
                    else s.pb.score < s.score
                ):
                    s.status = SubmitStatus.BEST
                    s.pb.status = SubmitStatus.PASSED

                    await services.sql.execute(
                        "UPDATE scores SET status = 2 WHERE user_id = %s AND gamemode = %s "
                        "AND map_md5 = %s AND mode = %s AND status = 3",
                        (s.player.id, s.gamemode, s.map.map_md5, s.mode.value),
                    )
                else:
                    s.status = SubmitStatus.PASSED
            else:
                # if we find no old personal best
                # we can just set the status to best
                s.status = SubmitStatus.BEST
        else:
            s.status = SubmitStatus.FAILED

        return s

    async def calculate_position(self) -> None:
        ret = await services.sql.fetch(
            "SELECT COUNT(*) AS rank FROM scores s "
            "INNER JOIN beatmaps b ON b.map_md5 = s.map_md5 "
            "INNER JOIN users u ON u.id = s.user_id "
            "WHERE s.score > %s AND s.gamemode = %s "
            "AND b.map_md5 = %s AND u.privileges & 4 "
            "AND s.status = 3 AND s.mode = %s "
            "ORDER BY s.score DESC, s.submitted DESC",
            (self.score, self.gamemode, self.map.map_md5, self.mode.value),
        )

        self.position = ret["rank"] + 1

    async def save_to_db(self) -> int:
        return await services.sql.execute(
            "INSERT INTO scores (map_md5, user_id, score, pp, "
            "count_300, count_100, count_50, count_geki, "
            "count_katu, count_miss, max_combo, accuracy, "
            "perfect, rank, mods, status, playtime, "
            " mode, submitted, gamemode, awards_pp) VALUES "
            "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                self.map.map_md5,
                self.player.id,
                self.score,
                self.pp,
                self.count_300,
                self.count_100,
                self.count_50,
                self.count_geki,
                self.count_katu,
                self.count_miss,
                self.max_combo,
                self.accuracy,
                self.perfect,
                self.rank,
                self.mods.value,
                self.status.value,
                self.playtime,
                self.mode.value,
                self.submitted,
                self.gamemode.value,
                self._awards_pp,
            ),
        )

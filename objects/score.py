import math
import time

from utils.score import calculate_accuracy
from enum import IntEnum
from typing import Optional, Union
from base64 import b64decode
from objects import services
from dataclasses import dataclass
from rina_pp_pyb import GameMode, Performance, Beatmap as BMap

from constants.mods import Mods
from objects.beatmap import Beatmap
from constants.playmode import Gamemode, Mode
from constants.playmode import Mode
from py3rijndael.rijndael import RijndaelCbc
from py3rijndael.paddings import ZeroPadding
from objects.player import Player
from databases.interfaces import Record


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

        self.mode: Mode = Mode.OSU
        self.status: SubmitStatus = SubmitStatus.FAILED

        self.mods: Mods = Mods.NONE
        self.gamemode: Gamemode = Gamemode.VANILLA

        self.playtime: int = 0
        self.submitted: int = math.ceil(time.time())

        self.position: int = 0

        self.previous_best: Union["Score", None] = None

        self.awards_pp: bool = False

    @property
    def web_format(self) -> str:
        return (
            f"\n{self.id}|{self.player.username}|{self.score if self.gamemode == Gamemode.VANILLA else math.ceil(self.pp)}|"
            f"{self.max_combo}|{self.count_50}|{self.count_100}|{self.count_300}|{self.count_miss}|"
            f"{self.count_katu}|{self.count_geki}|{self.perfect}|{self.mods}|{self.player.id}|"
            f"{self.position}|{self.submitted}|1"
        )

    @classmethod
    async def from_sql(cls, data: Record) -> "Score":
        score = cls()

        score.id = data["id"]

        score.score = data["score"]
        score.pp = data["pp"]

        score.count_300 = data["count_300"]
        score.count_100 = data["count_100"]
        score.count_50 = data["count_50"]
        score.count_geki = data["count_geki"]
        score.count_katu = data["count_katu"]
        score.count_miss = data["count_miss"]

        score.total_hits = score.count_300 + score.count_100 + score.count_50

        score.max_combo = data["max_combo"]
        score.accuracy = data["accuracy"]

        score.perfect = data["perfect"]

        score.rank = data["rank"]
        score.mods = Mods(data["mods"])

        score.playtime = data["playtime"]

        score.status = SubmitStatus(data["status"])
        score.mode = Mode(data["mode"])

        score.submitted = data["submitted"]

        score.gamemode = Gamemode(data["gamemode"])

        return score

    @classmethod
    async def from_submission(
        cls,
        score_enc: bytes,
        iv: bytes,
        key: str,
        quit: int,
    ) -> Optional["Score"]:
        score_latin = b64decode(score_enc).decode("latin_1")
        iv_latin = b64decode(iv).decode("latin_1")

        data = (
            RijndaelCbc(key, iv_latin, ZeroPadding(32), 32)  # type: ignore
            .decrypt(score_latin)
            .decode()
            .split(":")
        )

        score = cls()

        if not (player := services.players.get(data[1].rstrip())):
            return

        score.player = player

        if not (map := await services.beatmaps.get(data[0])):
            return

        score.map = map

        score.count_300 = int(data[3])
        score.count_100 = int(data[4])
        score.count_50 = int(data[5])
        score.count_geki = int(data[6])
        score.count_katu = int(data[7])
        score.count_miss = int(data[8])
        score.score = int(data[9])
        score.max_combo = int(data[10])

        score.mode = Mode(int(data[15]))

        score.accuracy = calculate_accuracy(
            score.mode,
            score.count_300,
            score.count_100,
            score.count_50,
            score.count_geki,
            score.count_katu,
            score.count_miss,
        )

        score.total_hits = score.count_300 + score.count_100 + score.count_50
        score.perfect = score.max_combo == score.map.max_combo
        score.rank = data[12]
        score.mods = Mods(int(data[13]))

        mods = int(data[13])
        score.gamemode = Gamemode.RELAX if mods & Mods.RELAX else Gamemode.VANILLA

        passed = data[14] == "True"

        await score.calculate_position()

        if score.map.approved.has_leaderboard:
            map = BMap(path=f".data/beatmaps/{score.map.file}")

            if score.mode != map.mode:
                map.convert(GameMode(score.mode.value))

            perf = Performance(
                n300=score.count_300,
                n100=score.count_100,
                n50=score.count_50,
                misses=score.count_miss,
                n_geki=score.count_geki,
                n_katu=score.count_katu,
                combo=score.max_combo,
                mods=score.mods,
            ).calculate(map)

            score.pp = perf.pp

            if math.isnan(score.pp) or math.isinf(score.pp):
                score.pp = 0

            score.awards_pp = score.map.approved.awards_pp

        if quit:
            score.status = SubmitStatus.QUIT
            return score

        if not passed:
            score.status = SubmitStatus.FAILED
            return score

        # find our previous best score on the map
        if not (
            prev_best := await services.database.fetch_one(
                "SELECT id, user_id, map_md5, score, pp, count_300, count_100, "
                "count_50, count_geki, count_katu, count_miss, "
                "max_combo, accuracy, perfect, rank, mods, status, "
                "playtime, mode, submitted, gamemode FROM scores "
                "WHERE user_id = :user_id AND gamemode = :gamemode "
                "AND map_md5 = :map_md5 AND mode = :mode AND status = 3",
                {
                    "user_id": score.player.id,
                    "gamemode": score.gamemode,
                    "map_md5": score.map.map_md5,
                    "mode": score.mode.value,
                },
            )
        ):
            # if we find no old personal best
            # we can just set the status to best
            score.status = SubmitStatus.BEST
            return score

        score.previous_best = await Score.from_sql(prev_best)

        # identical to `calculate_position(self)`
        position = await services.database.fetch_val(
            "SELECT COUNT(*) FROM scores s "
            "INNER JOIN beatmaps b ON b.map_md5 = s.map_md5 "
            "INNER JOIN users u ON u.id = s.user_id "
            "WHERE s.score > :pb_score AND s.gamemode = :gamemode "
            "AND s.map_md5 = :map_md5 AND u.privileges & 4 "
            "AND s.status = 3 AND s.mode = :mode "
            "ORDER BY s.score DESC, s.submitted DESC",
            {
                "pb_score": score.previous_best.score,
                "gamemode": score.previous_best.gamemode.value,
                "map_md5": score.map.map_md5,
                "mode": score.previous_best.mode.value,
            },
        )
        score.previous_best.position = position + 1

        # if we found a personal best score
        # that has more score on the map,
        # we set it to passed.
        if (
            score.previous_best.pp < score.pp
            if score.gamemode != Gamemode.VANILLA
            else score.previous_best.score < score.score
        ):
            score.status = SubmitStatus.BEST
            score.previous_best.status = SubmitStatus.PASSED

            await services.database.execute(
                "UPDATE scores SET status = 2, awards_pp = 0 WHERE user_id = :user_id "
                "AND gamemode = :gamemode AND map_md5 = :map_md5 AND mode = :mode AND status = 3",
                {
                    "user_id": score.player.id,
                    "gamemode": score.gamemode,
                    "map_md5": score.map.map_md5,
                    "mode": score.mode.value,
                },
            )
        else:
            score.status = SubmitStatus.PASSED

        return score

    async def calculate_position(self) -> None:
        position = await services.database.fetch_val(
            "SELECT COUNT(*) FROM scores s "
            "INNER JOIN beatmaps b ON b.map_md5 = s.map_md5 "
            "INNER JOIN users u ON u.id = s.user_id "
            "WHERE s.score > :score AND s.gamemode = :gamemode "
            "AND s.map_md5 = :map_md5 AND u.privileges & 4 "
            "AND s.status = 3 AND s.mode = :mode "
            "ORDER BY s.score DESC, s.submitted DESC",
            {
                "score": self.score,
                "gamemode": self.gamemode.value,
                "map_md5": self.map.map_md5,
                "mode": self.mode.value,
            },
        )

        self.position = position + 1

    async def save_to_db(self) -> int:
        return await services.database.execute(
            "INSERT INTO scores (map_md5, user_id, score, pp, count_300, count_100, count_50, count_geki, "
            "count_katu, count_miss, max_combo, accuracy, perfect, rank, mods, status, playtime, mode, submitted, "
            "gamemode, awards_pp) "
            "VALUES (:map_md5, :user_id, :score, :pp, :count_300, :count_100, :count_50, :count_geki, "
            ":count_katu, :count_miss, :max_combo, :accuracy, :perfect, :rank, :mods, :status, :playtime, "
            ":mode, :submitted, :gamemode, :awards_pp)",
            {
                "map_md5": self.map.map_md5,
                "user_id": self.player.id,
                "score": self.score,
                "pp": self.pp,
                "count_300": self.count_300,
                "count_100": self.count_100,
                "count_50": self.count_50,
                "count_geki": self.count_geki,
                "count_katu": self.count_katu,
                "count_miss": self.count_miss,
                "max_combo": self.max_combo,
                "accuracy": self.accuracy,
                "perfect": self.perfect,
                "rank": self.rank,
                "mods": self.mods.value,
                "status": self.status.value,
                "playtime": self.playtime,
                "mode": self.mode.value,
                "submitted": self.submitted,
                "gamemode": self.gamemode.value,
                "awards_pp": self.awards_pp,
            },
        )

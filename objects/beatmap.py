import copy
import os
import aiohttp
import settings

from typing import Union
from objects import services

from constants.mods import Mods
from constants.playmode import Mode
from constants.beatmap import Approved


class Beatmap:
    def __init__(self):
        self.server: str = "bancho"
        self.set_id: int = 0
        self.map_id: int = 0
        self.map_md5: str = ""

        self.title: str = ""
        self.title_unicode: str = ""  # added
        self.version: str = ""
        self.artist: str = ""
        self.artist_unicode: str = ""  # added
        self.creator: str = ""
        self.creator_id: int = 0

        self.stars: float = 0.0
        self.od: float = 0.0
        self.ar: float = 0.0
        self.hp: float = 0.0
        self.cs: float = 0.0
        self.mode: int = 0
        self.bpm: float = 0.0
        self.max_combo: int = 0

        self.submit_date: str = "0"
        self.approved_date: str = "0"
        self.latest_update: str = "0"

        self.hit_length: float = 0.0
        self.drain: int = 0

        self.plays: int = 0
        self.passes: int = 0
        self.favorites: int = 0

        self.rating: float = 0.0  # added

        self.approved: Approved = Approved.PENDING
        self.scores: int = 0

    @property
    def file(self) -> str:
        return f"{self.map_id}.osu"

    @property
    def pass_procent(self) -> float:
        return self.passes / self.plays * 100

    @property
    def full_title(self) -> str:
        return f"{self.artist} - {self.title} [{self.version}]"

    @property
    def display_title(self) -> str:
        # You didn't see this
        return f"[bold:0,size:20]{self.artist_unicode}|{self.title_unicode}"

    @property
    def url(self) -> str:
        return f"https://{services.domain}/beatmapsets/{self.set_id}#{self.map_id}"

    @property
    def embed(self) -> str:
        return f"[{self.url} {self.full_title}]"

    def length_in_minutes_seconds(self, mods: Mods = Mods.NONE) -> str:
        length = copy.copy(self.hit_length)

        if mods & Mods.DOUBLETIME or mods & Mods.NIGHTCORE:
            length -= length * 0.33
        elif mods & Mods.HALFTIME:
            length *= 1.33

        minutes, seconds = divmod(length, 60)
        return f"{int(minutes)}:{int(seconds):0>2}"

    @property
    def web_format(self) -> str:
        return f"{self.approved.to_osu}|false|{self.map_id}|{self.set_id}|{self.scores}\n0\n{self.display_title}\n{self.rating}"

    @staticmethod
    def add_chart(name: str, prev: int | float = 0.0, after: int | float = 0.0) -> str:
        return f"{name}Before:{prev if prev else ''}|{name}After:{after}"

    @classmethod
    async def _get_beatmap_from_sql(
        cls, hash: str = "", beatmap_id: int = 0, set_id: int = 0
    ) -> Union["Beatmap", None]:
        b = cls()

        params = (
            ("set_id", set_id)
            if set_id
            else ("map_md5", hash) if hash else ("map_id", beatmap_id)
        )

        ret = await services.sql.fetch(
            "SELECT server, set_id, map_id, map_md5, title, title_unicode, "
            "version, artist, artist_unicode, creator, creator_id, stars, "
            "od, ar, hp, cs, mode, bpm, approved, submit_date, approved_date, "
            "latest_update, length, drain, plays, passes, favorites, rating "
            f"FROM beatmaps WHERE {params[0]} = %s ORDER BY stars DESC",
            (params[1]),
        )

        if not ret:
            return

        b.server = ret["server"]
        b.set_id = ret["set_id"]
        b.map_id = ret["map_id"]
        b.map_md5 = ret["map_md5"]

        b.title = ret["title"]
        b.title_unicode = ret["title_unicode"]  # added
        b.version = ret["version"]
        b.artist = ret["artist"]
        b.artist_unicode = ret["artist_unicode"]  # added
        b.creator = ret["creator"]
        b.creator_id = ret["creator_id"]

        b.stars = ret["stars"]
        b.od = ret["od"]
        b.ar = ret["ar"]
        b.hp = ret["hp"]
        b.cs = ret["cs"]
        b.mode = ret["mode"]
        b.bpm = ret["bpm"]

        if settings.RANK_ALL_MAPS:
            b.approved = Approved.RANKED
        else:
            b.approved = Approved(ret["approved"])

        b.submit_date = ret["submit_date"]
        b.approved_date = ret["approved_date"]
        b.latest_update = ret["latest_update"]

        b.hit_length = ret["length"]
        b.drain = ret["drain"]

        b.plays = ret["plays"]
        b.passes = ret["passes"]
        b.favorites = ret["favorites"]

        b.rating = ret["rating"]

        return b

    async def add_to_db(self) -> None:
        if await services.sql.fetch(
            "SELECT 1 FROM beatmaps WHERE map_md5 = %s LIMIT 1", (self.map_md5)
        ):
            return  # ignore beatmaps there are already in db

        values = [*self.__dict__.values()][:-2]
        values.append(self.approved.value)

        await services.sql.execute(
            "INSERT INTO beatmaps (server, set_id, map_id, map_md5, title, title_unicode, "
            "version, artist, artist_unicode, creator, creator_id, stars, "
            "od, ar, hp, cs, mode, bpm, max_combo, submit_date, approved_date, "
            "latest_update, length, drain, plays, passes, favorites, rating, approved) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            values,
        )

        services.logger.info(f"Saved {self.full_title} ({self.map_md5}) into database")

    async def map_md5_check(self, map_md5: str, map_id: int) -> bool:
        md5_check = await self._get_beatmap_from_sql(beatmap_id=map_id)

        if md5_check:
            if md5_check.map_md5 != map_md5:
                # just delete that shit
                await services.sql.execute(
                    "DELETE FROM beatmaps WHERE map_id = %s", (map_id)
                )
                services.logger.info(
                    "Removed previous saved beatmap from database and added the updated one."
                )

                # also delete previous .osu file in .data/beatmaps
                if os.path.exists(f".data/beatmaps/{map_id}.osu"):
                    os.remove(f".data/beatmaps/{map_id}.osu")

                    services.logger.info(
                        "Removed previous `.osu` file from .data/beatmaps"
                    )

                return True

        return False

    @classmethod
    async def _get_beatmap_from_osuapi(
        cls, hash: str, beatmap_id: int, set_id: int
    ) -> Union["Beatmap", None]:
        b = cls()

        async with aiohttp.ClientSession() as session:
            # get the beatmap with its hash
            params = (
                ("s", set_id)
                if set_id
                else ("b", beatmap_id) if beatmap_id else ("h", hash)
            )

            async with session.get(
                f"https://osu.ppy.sh/api/get_beatmaps?k={services.osu_key}&{params[0]}={params[1]}"
            ) as resp:
                if not resp or resp.status != 200:
                    return

                if not (b_data := await resp.json()):
                    return

                ret = b_data[0]

        b.set_id = int(ret["beatmapset_id"])
        b.map_id = int(ret["beatmap_id"])

        await b.map_md5_check(hash, b.map_id)

        b.map_md5 = ret["file_md5"]

        b.title = ret["title"]
        b.title_unicode = ret["title_unicode"] or ret["title"]  # added
        b.version = ret["version"]
        b.artist = ret["artist"]
        b.artist_unicode = ret["artist_unicode"] or ret["artist"]  # added
        b.creator = ret["creator"]
        b.creator_id = int(ret["creator_id"])

        b.stars = float(ret["difficultyrating"])
        b.od = float(ret["diff_overall"])
        b.ar = float(ret["diff_approach"])
        b.hp = float(ret["diff_drain"])
        b.cs = float(ret["diff_size"])
        b.mode = Mode(int(ret["mode"])).value
        b.bpm = float(ret["bpm"])
        b.max_combo = (
            0 if ret["max_combo"] is None else int(ret["max_combo"])
        )  # fix taiko and mania "null" combo

        # for some reason, the api shows approved as one behind?
        if settings.RANK_ALL_MAPS:
            b.approved = Approved.RANKED
        else:
            if (ranked_status := Approved(int(ret["approved"]))) <= Approved.PENDING:
                b.approved = ranked_status
            else:
                b.approved = Approved(ranked_status + 1)

        b.submit_date = ret["submit_date"]

        if ret["approved_date"]:
            b.approved_date = ret["approved_date"]
        else:
            b.approved_date = "0"

        b.latest_update = ret["last_update"]

        b.hit_length = float(ret["total_length"])
        b.drain = int(ret["hit_length"])

        b.plays = 0
        b.passes = 0
        b.favorites = 0

        b.rating = float(ret["rating"])

        await b.add_to_db()

        return b

    @classmethod
    async def get_beatmap(
        cls, hash: str = "", beatmap_id: int = 0, set_id: int = 0
    ) -> Union["Beatmap", None]:
        self = cls()  # trollface

        if not (ret := await self._get_beatmap_from_sql(hash, beatmap_id, set_id)):
            if not (
                ret := await self._get_beatmap_from_osuapi(hash, beatmap_id, set_id)
            ):
                return

        return ret

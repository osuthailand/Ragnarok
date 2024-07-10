import copy
import os
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
    def filename(self) -> str:
        return f"{self.artist} - {self.title} ({self.creator}) [{self.version}].osu"

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

    def play_duration(self, mods: Mods = Mods.NONE) -> str:
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
    async def get_from_db(
        cls, map_md5: str = "", map_id: int = 0, set_id: int = 0
    ) -> Union["Beatmap", None]:
        map = cls()

        params = (
            ("set_id", set_id)
            if set_id
            else ("map_md5", map_md5) if map_md5 else ("map_id", map_id)
        )

        map_db = await services.database.fetch_one(
            "SELECT server, set_id, map_id, map_md5, title, title_unicode, "
            "version, artist, artist_unicode, creator, creator_id, stars, "
            "od, ar, hp, cs, mode, bpm, approved, submit_date, approved_date, "
            "latest_update, length, drain, plays, passes, favorites, rating "
            f"FROM beatmaps WHERE {params[0]} = :param ORDER BY stars DESC",
            {"param": params[1]},
        )

        if not map_db:
            return

        map.server = map_db["server"]
        map.set_id = map_db["set_id"]
        map.map_id = map_db["map_id"]
        map.map_md5 = map_db["map_md5"]

        map.title = map_db["title"]
        map.title_unicode = map_db["title_unicode"]  # added
        map.version = map_db["version"]
        map.artist = map_db["artist"]
        map.artist_unicode = map_db["artist_unicode"]  # added
        map.creator = map_db["creator"]
        map.creator_id = map_db["creator_id"]

        map.stars = map_db["stars"]
        map.od = map_db["od"]
        map.ar = map_db["ar"]
        map.hp = map_db["hp"]
        map.cs = map_db["cs"]
        map.mode = map_db["mode"]
        map.bpm = map_db["bpm"]

        if settings.RANK_ALL_MAPS:
            map.approved = Approved.RANKED
        else:
            map.approved = Approved(map_db["approved"])

        map.submit_date = map_db["submit_date"]
        map.approved_date = map_db["approved_date"]
        map.latest_update = map_db["latest_update"]

        map.hit_length = map_db["length"]
        map.drain = map_db["drain"]

        map.plays = map_db["plays"]
        map.passes = map_db["passes"]
        map.favorites = map_db["favorites"]

        map.rating = map_db["rating"]

        return map

    async def add_to_db(self) -> None:
        if await services.database.fetch_one(
            "SELECT 1 FROM beatmaps WHERE map_md5 = :map_md5 LIMIT 1",
            {"map_md5": self.map_md5},
        ):
            return  # ignore beatmaps there are already in db

        obj = self.__dict__.copy()
        obj.pop("scores")
        obj.pop("server")
        obj["approved"] = self.approved.value

        await services.database.execute(
            "INSERT INTO beatmaps (server, set_id, map_id, map_md5, title, "
            "title_unicode, version, artist, artist_unicode, creator, creator_id, "
            "stars, od, ar, hp, cs, mode, bpm, max_combo, submit_date, approved_date, "
            "latest_update, length, drain, plays, passes, favorites, rating, approved) "
            "VALUES ('bancho', :set_id, :map_id, :map_md5, :title, :title_unicode, :version, "
            ":artist, :artist_unicode, :creator, :creator_id, :stars, :od, :ar, :hp, :cs, "
            ":mode, :bpm, :max_combo, :submit_date, :approved_date, :latest_update, :hit_length, "
            ":drain, :plays, :passes, :favorites, :rating, :approved)",
            obj,
        )

        services.logger.info(f"Saved {self.full_title} ({self.map_md5}) into database")

    async def check_for_updates(self, map_md5: str, map_id: int) -> bool:
        map = await self.get_from_db(map_id=map_id)

        if map:
            if map.map_md5 != map_md5:
                # just delete that shit
                await services.database.execute(
                    "DELETE FROM beatmaps WHERE map_id = :map_id", {"map_id": map_id}
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
    def from_osu_api(cls, osu_map: dict[str, str]) -> "Beatmap":
        map = cls()
        map.set_id = int(osu_map["beatmapset_id"])
        map.map_id = int(osu_map["beatmap_id"])
        map.map_md5 = osu_map["file_md5"]
        map.title = osu_map["title"]
        map.title_unicode = osu_map["title_unicode"] or osu_map["title"]  # added
        map.version = osu_map["version"]
        map.artist = osu_map["artist"]
        map.artist_unicode = osu_map["artist_unicode"] or osu_map["artist"]  # added
        map.creator = osu_map["creator"]
        map.creator_id = int(osu_map["creator_id"])
        map.stars = float(osu_map["difficultyrating"])
        map.od = float(osu_map["diff_overall"])
        map.ar = float(osu_map["diff_approach"])
        map.hp = float(osu_map["diff_drain"])
        map.cs = float(osu_map["diff_size"])
        map.mode = Mode(int(osu_map["mode"])).value
        map.bpm = float(osu_map["bpm"])
        map.max_combo = (
            0 if osu_map["max_combo"] is None else int(osu_map["max_combo"])
        )  # fix taiko and mania "null" combo

        if settings.RANK_ALL_MAPS:
            map.approved = Approved.RANKED
        else:
            approved_status = int(osu_map["approved"])

            # conver approved status to ragnarok's desired
            ragnarok_approved = {4: 5, 3: 4, 2: 3, 1: 2}

            if approved_status in ragnarok_approved:
                approved_status = ragnarok_approved[approved_status]

            map.approved = Approved(approved_status)

        map.submit_date = osu_map["submit_date"]

        if osu_map["approved_date"]:
            map.approved_date = osu_map["approved_date"]
        else:
            map.approved_date = "0"

        map.latest_update = osu_map["last_update"]
        map.hit_length = float(osu_map["total_length"])
        map.drain = int(osu_map["hit_length"])
        map.plays = 0
        map.passes = 0
        map.favorites = 0
        map.rating = float(osu_map["rating"])

        return map

    @classmethod
    async def get_from_osu_api(
        cls, map_md5: str = "", map_id: int = 0, set_id: int = 0
    ) -> Union["Beatmap", list["Beatmap"], None]:
        params = (
            ("s", set_id) if set_id else ("b", map_id) if map_id else ("h", map_md5)
        )

        response = await services.http_client_session.get(
            f"https://osu.ppy.sh/api/get_beatmaps?k={services.osu_key}&{params[0]}={params[1]}"
        )

        if not response or response.status != 200:
            return

        if not (decoded := await response.json()):
            return

        maps = decoded

        if set_id:
            map_set = []

            for map in maps:
                osu_map = Beatmap.from_osu_api(map)
                map_set.append(osu_map)

            return map_set

        map = Beatmap.from_osu_api(maps[0])
        await map.check_for_updates(map.map_md5, map.map_id)
        await map.add_to_db()

        return map

    @classmethod
    async def get(
        cls, map_md5: str = "", map_id: int = 0, set_id: int = 0
    ) -> Union["Beatmap", list["Beatmap"], None]:
        map = cls()

        if not (ret := await map.get_from_db(map_md5, map_id, set_id)):
            if not (ret := await map.get_from_osu_api(map_md5, map_id, set_id)):
                return

        return ret

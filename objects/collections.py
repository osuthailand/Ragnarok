from typing import Any, Iterator

from objects import services
from objects.bot import Bot
from objects.channel import Channel
from objects.match import Match
from objects.player import Player
from objects.beatmap import Beatmap


class Tokens:
    def __init__(self):
        self.players: list[Player | Bot] = []

    def __iter__(self) -> Iterator[Player]:
        return iter(self.players)

    def __len__(self) -> int:
        return len(self.players)

    def add(self, p: Player | Bot) -> None:
        self.players.append(p)

    def remove(self, p: Player) -> None:
        self.players.remove(p)

    def get(self, value: str | int) -> Player | None:
        for p in self.players:
            if (
                p.id == value
                or p.username == value
                or p.token == value
                or p.safe_name == value
            ):
                return p

    async def get_offline(self, value: str | int) -> Player | None:
        if p := self.get(value):
            return p

        if isinstance(value, int):
            if p := await self.from_sql_by_id(value):
                return p
        else:
            if p := await self.from_sql_by_name(value):
                return p

    async def from_sql_by_name(self, value: str | int) -> Player | None:
        data = await services.sql.fetch(
            "SELECT username, id, privileges, passhash, country FROM users "
            "WHERE (username = %s OR safe_username = %s)",
            (value, value),
        )

        if not data:
            return

        p = Player(**data)

        return p

    async def from_sql_by_id(self, value: str | int) -> Player | None:
        data = await services.sql.fetch(
            "SELECT username, id, privileges, passhash, country FROM users "
            "WHERE id = %s",
            (value),
        )

        if not data:
            return

        p = Player(**data)

        return p

    def enqueue(self, packet: bytes) -> None:
        for p in self.players:
            p.enqueue(packet)


class Channels:
    def __init__(self):
        self.channels: list[Channel] = []

    def __iter__(self):
        return iter(self.channels)

    def add(self, chan: Channel) -> None:
        self.channels.append(chan)

    def remove(self, c: Channel) -> None:
        self.channels.remove(c)

    def get(self, name: str) -> Channel | None:
        for chan in self.channels:
            if chan.name == name:
                return chan


class Matches:
    def __init__(self):
        self.matches: list[Match] = []

    def __iter__(self):
        return iter(self.matches)

    def __len__(self):
        return len(self.matches)

    def remove(self, m: Match):
        if m in self.matches:
            self.matches.remove(m)

    def get(self, match_id: int) -> Match:  # type: ignore
        for match in self.matches:
            if match_id == match.match_id:
                return match

    def add(self, m: Match):
        self.matches.append(m)


class Beatmaps:
    def __init__(self):
        self.beatmaps: dict[str, Beatmap] = {}

    def __iter__(self):
        return iter(self.beatmaps)

    def __getitem__(self, item: str) -> Beatmap:
        return self.beatmaps[item]

    def remove(self, map_md5: str) -> None:
        if map_md5 in self.beatmaps:
            self.beatmaps.pop(map_md5)

    async def get(self, map_md5: str) -> Beatmap | None:
        if map_md5 in self.beatmaps:
            return self.beatmaps[map_md5]

        if not (b := await Beatmap.get_beatmap(map_md5)):
            services.logger.critical(f"Failed to get beatmaps with hash {map_md5}")
            return

        # when getting from the api, it'll save into cache
        self.beatmaps[map_md5] = b
        return b

    async def get_by_map_id(self, map_id: int) -> Beatmap | None:
        if not (b := await Beatmap.get_beatmap(beatmap_id=map_id)):
            services.logger.critical(f"Failed to get beatmaps with map_id {map_id}")
            return

        self.beatmaps[b.map_md5] = b
        return b

    async def get_by_set_id(self, set_id: int) -> Beatmap | None:
        if not (b := await Beatmap.get_beatmap(set_id=set_id)):
            services.logger.critical(f"Failed to get beatmaps with map_id {set_id}")
            return

        self.beatmaps[b.map_md5] = b
        return b

    def get_maps_from_set_id(self, set_id: int) -> list[str]:
        h = []

        for key, map in self.beatmaps.items():
            if map.set_id == set_id:
                h.append(key)

        return h

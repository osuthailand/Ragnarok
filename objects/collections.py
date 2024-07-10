from typing import Iterator

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
        for player in self.players:
            if (
                player.id == value
                or player.username == value
                or player.token == value
                or player.safe_username == value
            ):
                return player

    async def get_offline(self, value: str | int) -> Player | None:
        if player := self.get(value):
            return player

        if isinstance(value, int):
            if player := await self.from_sql_by_id(value):
                return player
        else:
            if player := await self.from_sql_by_name(value):
                return player

    async def from_sql_by_name(self, value: str) -> Player | None:
        user = await services.database.fetch_one(
            "SELECT username, id, privileges, passhash, country FROM users "
            "WHERE (username = :value OR safe_username = :value)",
            {"value": value},
        )

        if not user:
            return

        player = Player(**dict(user))

        return player

    async def from_sql_by_id(self, value: int) -> Player | None:
        user = await services.database.fetch_one(
            "SELECT username, id, privileges, passhash,  "
            "country FROM users WHERE id = :user_id",
            {"user_id": value},
        )

        if not user:
            return

        player = Player(**dict(user))

        return player

    def enqueue(self, data: bytes) -> None:
        for player in self.players:
            player.enqueue(data)


class Channels:
    def __init__(self):
        self.channels: list[Channel] = []

    def __iter__(self):
        return iter(self.channels)

    def add(self, channel: Channel) -> None:
        self.channels.append(channel)

    def remove(self, channel: Channel) -> None:
        self.channels.remove(channel)

    def get(self, name: str) -> Channel | None:
        for channel in self.channels:
            if channel.name == name:
                return channel


class Matches:
    def __init__(self):
        self.matches: list[Match] = []

    def __iter__(self):
        return iter(self.matches)

    def __len__(self):
        return len(self.matches)

    def remove(self, match: Match):
        if match in self.matches:
            self.matches.remove(match)

    def get(self, match_id: int) -> Match:  # type: ignore
        for match in self.matches:
            if match_id == match.id:
                return match

    def add(self, match: Match):
        self.matches.append(match)


class Beatmaps:
    def __init__(self):
        self.beatmaps: dict[str, Beatmap] = {}

    def __iter__(self):
        return iter(self.beatmaps)

    def __getitem__(self, map_md5: str) -> Beatmap:
        return self.beatmaps[map_md5]

    def remove(self, map_md5: str) -> None:
        if map_md5 in self.beatmaps:
            self.beatmaps.pop(map_md5)

    async def get(self, map_md5: str) -> Beatmap | None:
        if map_md5 in self.beatmaps:
            return self.beatmaps[map_md5]

        if not (map := await Beatmap.get(map_md5)):
            return

        if type(map) != Beatmap:
            return

        # when getting from the api, it'll save into cache
        self.beatmaps[map_md5] = map
        return map

    async def get_by_map_id(self, map_id: int) -> Beatmap | None:
        if not (map := await Beatmap.get(map_id=map_id)):
            services.logger.critical(
                f"failed to get beatmaps with map_id {map_id} (usually caused by the map not existing)"
            )
            return

        if type(map) != Beatmap:
            return

        self.beatmaps[map.map_md5] = map
        return map

    async def get_by_set_id(self, set_id: int) -> list[Beatmap] | None:
        if not (maps := await Beatmap.get(set_id=set_id)):
            services.logger.critical(
                f"failed to get beatmaps with map_id {set_id} (usually caused by the map not existing)"
            )
            return

        if type(maps) != list:
            return

        return maps

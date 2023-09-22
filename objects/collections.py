from typing import TYPE_CHECKING, Any, Iterator, Union

from objects import services
from objects.channel import Channel
from objects.match import Match
from objects.player import Player


class Tokens:
    def __init__(self):
        self.players: list[Player] = []

    def __iter__(self) -> Iterator[Player]:
        return iter(self.players)

    def add(self, p: Player) -> None:
        self.players.append(p)

    def remove(self, p: Player) -> None:
        self.players.remove(p)

    def get(self, value: str | int) -> Player:
        for p in self.players:
            if (
                p.id == value
                or p.username == value
                or p.token == value
                or p.safe_name == value
            ):
                return p

    async def get_offline(self, value: str | int) -> Player:
        if p := self.get(value):
            return p

        if isinstance(value, int):
            if p := await self.from_sql_by_id(value):
                return p
        else:
            if p := await self.from_sql_by_name(value):
                return p

    async def from_sql_by_name(self, value: str | int) -> Player:
        data = await services.sql.fetch(
            "SELECT username, id, privileges, passhash FROM users "
            "WHERE (username = %s OR safe_username = %s)",
            (value, value),
        )

        if not data:
            return

        p = Player(**data)

        return p

    async def from_sql_by_id(self, value: str | int) -> Player:
        data = await services.sql.fetch(
            "SELECT username, id, privileges, passhash FROM users "
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

    def add(self, data: dict[str, Any]) -> None:
        self.channels.append(Channel(**data))

    def remove(self, c: Channel) -> None:
        self.channels.remove(c)

    def get(self, name: str) -> Channel:
        for chan in self.channels:
            if chan._name == name or chan.name == name:
                return chan


class Matches:
    def __init__(self):
        self.matches: list["Match"] = []

    async def remove(self, m: "Match"):
        if m in self.matches:
            self.matches.remove(m)

    async def find(self, match_id: int) -> "Match":
        for match in self.matches:
            if match_id == match.match_id:
                return match

    async def add(self, m: "Match"):
        self.matches.append(m)

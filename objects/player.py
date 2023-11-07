from dataclasses import dataclass
import math
import time
import uuid
import asyncio
import aiohttp

from utils import log
from copy import copy
from packets import writer
from typing import Optional
from objects import services
from typing import TYPE_CHECKING

from constants.mods import Mods
from objects.match import Match
from objects.channel import Channel
from constants.levels import levels
from constants.playmode import Gamemode, Mode
from constants.match import SlotStatus
from objects.achievement import UserAchievement
from constants.player import PresenceFilter, bStatus, Privileges, country_codes

if TYPE_CHECKING:
    from objects.beatmap import Beatmap
    from objects.score import Score

class Player:
    def __init__(
        self,
        username: str,
        id: int,
        privileges: int,
        passhash: str,
        lon: float = 0.0,
        lat: float = 0.0,
        country: str = "XX",
        **kwargs,
    ) -> None:
        self.id: int = id
        self.username: str = username
        self.username_with_tag: str = ""
        self.safe_name: str = self.safe_username(self.username)
        self.privileges: int = privileges
        self.passhash: str = passhash

        self.country: str = country
        self.country_code: int = country_codes[self.country]

        self.ip: str = kwargs.get("ip", "127.0.0.1")
        self.longitude: float = lon
        self.latitude: float = lat
        self.timezone: int = kwargs.get("time_offset", 0) + 24
        self.client_version: str = kwargs.get("version", "0")
        self.in_lobby: bool = False

        self.token: str = kwargs.get("token", self.generate_token())

        self.presence_filter: PresenceFilter = PresenceFilter.NIL

        self.status: bStatus = bStatus.IDLE
        self.status_text: str = ""
        self.beatmap_md5: str = ""
        self.current_mods: Mods = Mods.NONE
        self.play_mode: Mode = Mode.OSU
        self.beatmap_id: int = -1

        self.achievements: list[UserAchievement] = []
        self.friends: set[int] = set()
        self.channels: list[Channel] = []
        self.spectators: list[Player] = []
        self.spectating: Player = None
        self.match: Match = None

        self.ranked_score: int = 0
        self.accuracy: float = 0.0
        self.playcount: int = 0
        self.total_score: int = 0
        self.level: float = 0.0
        self.rank: int = 0
        self.pp: int = 0

        self.total_hits: int = 0
        self.max_combo: int = 0

        self.gamemode: Gamemode = Gamemode.VANILLA

        self.block_unknown_pms: bool = kwargs.get("block_nonfriend", False)

        self.queue: bytearray = bytearray()

        self.login_time: float = time.time()
        self.last_update: float = 0.0

        self.bot: bool = False

        self.is_restricted: bool = not (self.privileges & Privileges.VERIFIED) and (
            not self.privileges & Privileges.PENDING
        )
        self.on_rina: bool = self.client_version.endswith("rina")
        self.is_staff: bool = self.privileges & Privileges.BAT
        self.is_verified: bool = not self.privileges & Privileges.PENDING

        self.last_np: "Beatmap" = None
        self.last_score: "Score" = None

    def __repr__(self) -> str:
        return (
            "Player("
            f'username="{self.username}", '
            f"id={self.id}, "
            f'token="{self.token}"'
            ")"
        )

    @property
    def embed(self) -> str:
        return f"[https://{services.domain}/users/{self.id} {self.username}]"

    @property
    def url(self) -> str:
        return f"https://{services.domain}/users/{self.id}"

    @staticmethod
    def generate_token() -> str:
        return str(uuid.uuid4())

    def safe_username(self, name: str) -> str:
        return name.lower().replace(" ", "_")

    def enqueue(self, packet: bytes) -> None:
        """``enqueue()`` adds a packet to the queue."""
        self.queue += packet

    def dequeue(self) -> bytes:
        """``dequeue()`` dequeues the current filled queue."""
        if self.queue:
            ret = bytes(self.queue)
            self.queue.clear()
            return ret

        return b""

    def shout(self, text: str) -> None:
        """``shout()`` alerts the player."""
        self.enqueue(writer.notification(text))

    def logout(self) -> None:
        """``logout()`` logs the player out."""
        if self.channels:
            while self.channels:
                self.channels[0].disconnect(self)

        if self.match:
            self.leave_match()

        if self.spectating:
            self.spectating.remove_spectator(self)

        services.players.remove(self)

        for player in services.players:
            if player != self:
                player.enqueue(writer.logout(self.id))

    def add_spectator(self, p: "Player") -> None:
        """``add_spectator()`` makes player `p` spectate the player"""
        spec_name = f"#spect_{self.id}"
        spec_channel = services.channels.get(spec_name)

        # create if there's no channel
        if not spec_channel:
            spec_channel = Channel(**
                {
                    "name": spec_name,
                    "display_name": "#spectator",
                    "description": f"spectator chat for {self.username}",
                    "ephemeral": True,
                    "public": False,
                }
            )

            services.channels.add(spec_channel)
            spec_channel.connect(self)
        
        spec_channel.connect(p)

        player_joined = writer.fellow_spectator_joined(p.id)

        for spectator in self.spectators:
            spectator.enqueue(player_joined)
            p.enqueue(writer.fellow_spectator_joined(spectator.id))
        
        self.spectators.append(p)
        p.spectating = self

        self.enqueue(writer.spectator_joined(p.id))
        log.info(f"{p.username} started spectating {self.username}")

    def remove_spectator(self, p: "Player") -> None:
        """``remove_spectator()`` makes player `p` stop spectating the player"""
        spec_channel = services.channels.get(f"#spect_{self.id}")
        self.spectators.remove(p)
        p.spectating = None

        #debug
        if not spec_channel:
            log.debug("WHAT!")
            return

        spec_channel.disconnect(p)

        fellow_stopped_spectating = writer.fellow_spectator_left(p.id)
        if not self.spectators:
            # if there are no spectators, make host disconnect
            # from spectator channel and removing the channel.
            spec_channel.disconnect(self)
        else:
            for s in self.spectators:
                s.enqueue(fellow_stopped_spectating)

        self.enqueue(writer.spectator_left(p.id))

    def join_match(self, m: Match, pwd: str = "") -> None:
        """``join_match()`` makes the player join a multiplayer match."""
        if self.match or pwd != m.match_pass or not m in services.matches:
            self.enqueue(writer.match_fail())
            return  # user is already in a match

        if (free_slot := m.get_free_slot()) == -1:
            self.enqueue(writer.match_fail())
            log.warn(f"{self.username} tried to join a full match ({m!r})")
            return

        self.match = m

        slot = m.slots[free_slot]

        slot.player = self
        slot.mods = Mods.NONE
        slot.status = SlotStatus.NOTREADY

        if m.host == self.id:
            slot.host = True

        if not self.match.chat:
            mc = Channel(**{
                "raw": f"#multi_{self.match.match_id}",
                "name": "#multiplayer",
                "description": self.match.match_name,
                "public": False,
                "ephemeral": True,
            })
            services.channels.add(mc)
            self.match.chat = mc

        self.match.chat.connect(self)

        self.match.connected.append(self)

        self.enqueue(writer.match_join(self.match))  # join success

        log.info(f"{self.username} joined {m}")
        self.match.enqueue_state(lobby=True)

    def leave_match(self) -> None:
        """``leave_match()`` leaves the multiplayer match, the user is in."""
        if not self.match or not (slot := self.match.find_user(self)):
            return

        self.match.chat.disconnect(self)

        m = copy(self.match)
        self.match = None

        slot.reset()
        m.connected.remove(self)

        log.info(f"{self.username} left {m}")

        # if that was the last person
        # to leave the multiplayer
        # delete the multi lobby
        if not m.connected:
            log.info(f"{m} is empty! Removing...")
            m.enqueue(writer.match_dispose(m.match_id), lobby=True)
            services.matches.remove(m)
            return

        if m.host == self.id:
            log.info("Host left, rotating host.")
            for slot in m.slots:
                if not slot.host and slot.status & SlotStatus.OCCUPIED:
                    m.transfer_host(slot)

                    break

        m.enqueue_state(immune={self.id}, lobby=True)

    def send_message(self, message, reciever: "Player"):
        reciever.enqueue(
            writer.send_message(
                sender=self.username,
                message=message,
                channel=reciever.username,
                id=self.id,
            )
        )

    async def get_clan_tag(self) -> None:
        clan_tag = await services.sql.fetch(
            "SELECT c.tag FROM clans c INNER JOIN users u ON c.id = u.clan_id "
            "WHERE u.id = %s",
            (self.id)
        )

        if not clan_tag:
            return

        self.username_with_tag = f"[{clan_tag["tag"]}] {self.username}"

    async def get_achievements(self) -> None:
        async for achievement in services.sql.iterall(
            "SELECT achievement_id, mode, gamemode FROM users_achievements "
            "WHERE user_id = %s",
            (self.id),
        ):
            # TODO: make mode and relax for user achievements
            if not (ach := services.get_achievement_by_id(achievement["achievement_id"])):
                log.fail(
                    f"user_achievements: Failed to fetch achievements (id: {
                        achievement['achievement_id']})"
                )
                return

            gamemode = Gamemode(achievement["gamemode"])
            mode = Mode(achievement["mode"])
            user_achievement = UserAchievement(
                **ach.__dict__,
                gamemode=gamemode,
                mode=mode
            )

            self.achievements.append(user_achievement)

    async def get_friends(self) -> None:
        async for player in services.sql.iterall(
            "SELECT user_id2 as id FROM friends WHERE user_id1 = %s", (self.id)
        ):
            self.friends.add(player["id"])

    async def handle_friend(self, user: int) -> None:
        if not (t := services.players.get(user)):
            return  # user isn't online; ignore

        # remove friend
        if await services.sql.fetch(
            "SELECT 1 FROM friends WHERE user_id1 = %s AND user_id2 = %s",
            (self.id, user),
        ):
            await services.sql.execute(
                "DELETE FROM friends WHERE user_id1 = %s AND user_id2 = %s",
                (self.id, user),
            )
            self.friends.remove(user)

            log.info(f"{self.username} removed {t.username} as friends.")
            return

        # add friend
        await services.sql.execute(
            "INSERT INTO friends (user_id1, user_id2) VALUES (%s, %s)", (self.id, user)
        )
        self.friends.add(user)

        log.info(f"{self.username} added {t.username} as friends.")

    async def restrict(self) -> None:
        if self.is_restricted:
            return  # just ignore if the user
            # is already restricted.

        self.privileges -= Privileges.VERIFIED

        await services.sql.execute(
            "UPDATE users SET privileges -= 4 WHERE id = %s", (self.id)
        )

        # remove player from leaderboards
        for mod in Gamemode:
            for mode in Mode:
                await services.redis.zrem(
                    f"ragnarok:leaderboard:{mod.value}:{mode.value}", self.id
                )

                # country rank
                await services.redis.zrem(
                    f"ragnarok:leaderboard:{mod.value}:{
                        self.country}:{mode.value}", self.id
                )

        # notify user
        self.shout("Your account has been put in restricted mode!")

        log.info(f"{self.username} has been put in restricted mode!")

    async def update_stats(self, s: "Score") -> None:
        se = ("std", "taiko", "catch", "mania")[s.mode]
        self.get_level()

        # important stuff
        await services.sql.execute(
            f"UPDATE {s.gamemode.table} SET pp_{
                se} = %s, playcount_{se} = %s, "
            f"accuracy_{se} = %s, total_score_{se} = %s, "
            f"ranked_score_{se} = %s, level_{se} = %s WHERE id = %s",
            (
                self.pp,
                self.playcount,
                round(self.accuracy, 2),
                self.total_score,
                self.ranked_score,
                self.level,
                self.id,
            ),
        )
        # less important
        await services.sql.execute(
            f"UPDATE {s.gamemode.table} SET total_hits_{
                se} = %s, "
            f"playtime_{se} = playtime_{
                se} + %s, max_combo_{se} = IF(max_combo_{se}<%s, %s, max_combo_{se}) "
            "WHERE id = %s",
            (self.total_hits, s.playtime, s.max_combo, s.max_combo, self.id)
        )

    def get_level(self):
        for idx, req_score in enumerate(levels):
            if req_score < self.total_score < levels[idx + 1]:
                self.level = idx + 1

    # used for background tasks
    async def check_loc(self):
        lon, lat, cc, c = await self.set_location(get=True)

        if lon != self.longitude:
            self.longitude = lon

        if lat != self.latitude:
            self.latitude = lat

        if c != self.country_code:
            self.country_code = c

        if cc != self.country:
            self.country = cc

        await self.save_location()

    async def set_location(self, get: bool = False):
        async with aiohttp.ClientSession() as sess:
            async with sess.get(
                f"http://ip-api.com/json/{
                    self.ip}?fields=status,message,countryCode,region,lat,lon"
            ) as resp:
                if not (ret := await resp.json()):
                    return  # sus

                if ret["status"] == "fail":
                    log.fail(
                        f"Unable to get {self.username}'s location. Response: {
                            ret['message']}"
                    )
                    return

                if not get:
                    self.latitude = ret["lat"]
                    self.longitude = ret["lon"]
                    self.country = ret["countryCode"]
                    self.country_code = country_codes[ret["countryCode"]]

                    return

                return (
                    ret["lat"],
                    ret["lon"],
                    ret["countryCode"],
                    country_codes[ret["countryCode"]],
                )

    async def save_location(self):
        await services.sql.execute(
            "UPDATE users SET lon = %s, lat = %s, country = %s WHERE id = %s",
            (self.longitude, self.latitude, self.country, self.id),
        )

    async def get_stats(self, gamemode: Gamemode = Gamemode.VANILLA, mode: Mode = Mode.OSU) -> dict:
        ret = await services.sql.fetch(
            f"SELECT {mode.to_db("ranked_score")}, {
                mode.to_db("total_score")}, "
            f"{mode.to_db("accuracy")}, {mode.to_db(
                "playcount")}, {mode.to_db("pp")}, "
            f"{mode.to_db("level")}, {mode.to_db("total_hits")}, {
                mode.to_db("max_combo")} "
            f"FROM {gamemode.table} "
            "WHERE id = %s",
            (self.id),
        )

        ret["rank"] = await self.get_rank(gamemode, mode)
        ret["country_rank"] = await self.get_country_rank(gamemode, mode)

        return ret

    async def get_rank(self, gamemode: Gamemode = Gamemode.VANILLA, mode: Mode = Mode.OSU) -> int:
        mod = (
            "vanilla" if gamemode == Gamemode.VANILLA else
            "relax" if gamemode == Gamemode.RELAX else
            "autopilot"  # gamemode == Gamemode.AUTOPILOT
        )
        _rank: int = await services.redis.zrevrank(
            f"ragnarok:leaderboard:{mod}:{mode}",
            str(self.id),
        )
        return _rank + 1 if _rank is not None else 0

    async def get_country_rank(self, gamemode: Gamemode = Gamemode.VANILLA, mode: Mode = Mode.OSU) -> int:
        mod = (
            "vanilla" if gamemode == Gamemode.VANILLA else
            "relax" if gamemode == Gamemode.RELAX else
            "autopilot"  # gamemode == Gamemode.AUTOPILOT
        )
        _rank: int = await services.redis.zrevrank(
            f"ragnarok:leaderboard:{mod}:{self.country}:{mode}",
            str(self.id),
        )
        return _rank + 1 if _rank is not None else 0

    async def update_rank(self, gamemode: Gamemode = Gamemode.VANILLA, mode: Mode = Mode.OSU) -> int:
        if not self.is_restricted:
            mod = (
                "vanilla" if gamemode == Gamemode.VANILLA else
                "relax" if gamemode == Gamemode.RELAX else
                "autopilot"  # gamemode == Gamemode.AUTOPILOT
            )
            await services.redis.zadd(
                f"ragnarok:leaderboard:{mod}:{mode}",
                {str(self.id): self.pp},
            )

            # country rank
            await services.redis.zadd(
                f"ragnarok:leaderboard:{mod}:{self.country}:{mode}",
                {str(self.id): self.pp},
            )

        return await self.get_rank(gamemode, mode)

    async def update_stats_cache(self) -> bool:
        ret = await self.get_stats(self.gamemode, self.play_mode)

        self.ranked_score = ret["ranked_score"]
        self.accuracy = ret["accuracy"]
        self.playcount = ret["playcount"]
        self.total_score = ret["total_score"]
        self.level = ret["level"]
        self.rank = ret["rank"]
        self.pp = math.ceil(ret["pp"])
        self.total_hits = ret["total_hits"]
        self.max_combo = ret["max_combo"]

        return True

    async def report(self, target: "Player", reason: str) -> None:
        await services.sql.execute(
            "INSERT INTO reports (reporter, reported, reason, time) "
            "VALUES (%s, %s, %s, %s)",
            (self.id, target.id, reason, int(time.time())),
        )

    async def log(self, note: str) -> None:
        await services.sql.execute(
            "INSERT INTO logs (user_id, note, time) VALUES (%s, %s, %s)",
            (self.id, note, int(time.time())),
        )

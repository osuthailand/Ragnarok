from enum import IntEnum
import math
import time
import uuid


from packets import writer
from objects import services
from typing import TYPE_CHECKING, Any, Union

from constants.mods import Mods
from objects.match import Match
from objects.channel import Channel
from constants.levels import levels
from constants.playmode import Gamemode, Mode
from constants.match import SlotStatus
from objects.achievement import UserAchievement
from constants.player import PresenceFilter, ActionStatus, Privileges, country_codes

if TYPE_CHECKING:
    from objects.beatmap import Beatmap
    from objects.score import Score


class LoggingType(IntEnum):
    ANY = -1
    HWID_CHECKS = 0
    RECALCULATIONS = 1
    RESTRICTIONS = 2
    # add more???


class Player:
    def __init__(
        self,
        username: str,
        id: int,
        privileges: int,
        passhash: str,
        longitude: float = 0.0,
        latitude: float = 0.0,
        country: str = "XX",
        **kwargs,
    ) -> None:
        self.id: int = id
        self.username: str = username
        self.username_with_tag: str = ""
        self.privileges: int = privileges
        self.passhash: str = passhash

        self.country: str = country
        self.country_code: int = country_codes[self.country]

        self.ip: str = kwargs.get("ip", "127.0.0.1")
        self.longitude: float = longitude
        self.latitude: float = latitude
        self.timezone: int = kwargs.get("time_offset", 0) + 24
        self.client_version: str = kwargs.get("version", "0")

        self.in_lobby: bool = False

        self.token: str = str(uuid.uuid4())

        self.presence_filter: PresenceFilter = PresenceFilter.NIL

        self.status: ActionStatus = ActionStatus.IDLE
        self.status_text: str = ""
        self.map_md5: str = ""
        self.map_id: int = -1
        self.current_mods: Mods = Mods.NONE

        self.play_mode: Mode = Mode.OSU
        self.gamemode: Gamemode = Gamemode.VANILLA

        self.achievements: list[UserAchievement] = []
        self.friends: set[int] = set()
        self.channels: list[Channel] = []
        self.spectators: list[Player] = []
        self.spectating: Player | None = None
        self.match: Match | None = None

        self.ranked_score: int = 0
        self.accuracy: float = 0.0
        self.playcount: int = 0
        self.total_score: int = 0
        self.level: float = 0.0
        self.rank: int = 0
        self.pp: int = 0
        self.total_hits: int = 0
        self.max_combo: int = 0

        self.queue: bytearray = bytearray()

        self.login_time: float = time.time()
        self.last_update: float = 0.0

        self.is_bot: bool = False

        self.last_np: Union["Beatmap", None] = None
        self.last_score: Union["Score", None] = None

    def __repr__(self) -> str:
        return (
            "Player("
            f'username="{self.username}", '
            f"id={self.id}, "
            f'token="{self.token}"'
            ")"
        )

    @property
    def is_restricted(self) -> bool:
        return not (self.privileges & Privileges.VERIFIED) and (
            not self.privileges & Privileges.PENDING
        )

    @property
    def is_staff(self) -> bool:
        return bool(self.privileges & Privileges.BAT)

    @property
    def using_rina(self) -> bool:
        return self.client_version.endswith("rina")

    @property
    def embed(self) -> str:
        return f"[https://{services.domain}/users/{self.id} {self.username}]"

    @property
    def url(self) -> str:
        return f"https://{services.domain}/users/{self.id}"

    @property
    def safe_username(self) -> str:
        return self.username.lower().replace(" ", "_")

    def __eq__(self, player: "Player") -> bool:
        return player.token == self.token

    def enqueue(self, data: bytes) -> None:
        """``enqueue()`` adds packet(s) to the queue."""
        self.queue += data

    def dequeue(self) -> bytes:
        """``dequeue()`` dequeues the current queue."""
        if self.queue:
            response = bytes(self.queue)
            self.queue.clear()
            return response

        return b""

    def shout(self, msg: str) -> None:
        """``shout()`` alerts the player."""
        self.enqueue(writer.notification(msg))

    async def verify(self) -> None:
        """`verify()` verifies the player and ensures the player doesn't have the `Privileges.PENDING` flag."""
        if self.privileges & Privileges.PENDING:
            await services.database.execute(
                "UPDATE users SET privileges = privileges - :pending WHERE id = :user_id",
                {"pending": Privileges.PENDING, "user_id": self.id},
            )
            self.privileges -= Privileges.PENDING
            self.privileges |= Privileges.VERIFIED

    async def update_latest_activity(self) -> None:
        """`update_latest_activity()` updates the players activity time."""
        self.last_update = time.time()

        await services.database.execute(
            "UPDATE users SET latest_activity_time = :time WHERE id = :id",
            {"time": self.last_update, "id": self.id},
        )

    async def logout(self) -> None:
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
            if player == self:
                continue

            player.enqueue(writer.logout(self.id))

        await services.redis.delete(f"ragnarok:session:{self.id}")

    def add_spectator(self, player: "Player") -> None:
        """``add_spectator()`` makes player `p` spectate the player"""
        channel_name = f"#spect_{self.id}"
        channel = services.channels.get(channel_name)

        # create if there's no channel
        if not channel:
            channel = Channel(
                **{
                    "name": channel_name,
                    "display_name": "#spectator",
                    "description": f"spectator chat for {self.username}",
                    "is_temporary": True,
                    "public": False,
                }
            )

            services.channels.add(channel)
            channel.connect(self)

        channel.connect(player)

        player_joined = writer.fellow_spectator_joined(player.id)

        for spectator in self.spectators:
            spectator.enqueue(player_joined)
            player.enqueue(writer.fellow_spectator_joined(spectator.id))

        self.spectators.append(player)
        player.spectating = self

        self.enqueue(writer.spectator_joined(player.id))
        services.logger.info(f"{player.username} started spectating {self.username}")

    def remove_spectator(self, player: "Player") -> None:
        """``remove_spectator()`` makes player `p` stop spectating the player"""
        self.spectators.remove(player)
        player.spectating = None

        channel = services.channels.get(f"#spect_{self.id}")

        if not channel:
            services.logger.debug("WHAT!")
            return

        channel.disconnect(player)

        fellow_stopped_spectating = writer.fellow_spectator_left(player.id)
        if not self.spectators:
            # if there are no spectators, make host disconnect
            # from spectator channel and removing the channel.
            channel.disconnect(self)
        else:
            for spectator in self.spectators:
                spectator.enqueue(fellow_stopped_spectating)

        self.enqueue(writer.spectator_left(player.id))

    def join_match(self, match: Match, password: str = "") -> None:
        """``join_match()`` makes the player join a multiplayer match."""
        if self.match or password != match.password or match not in services.matches:
            self.enqueue(writer.match_fail())
            return  # user is already in a match

        if (free_slot := match.get_free_slot()) is None:
            self.enqueue(writer.match_fail())
            services.logger.warn(
                f"{match!r}: {self.username} tried to join a full match"
            )
            return

        self.match = match

        slot = match.slots[free_slot]

        slot.player = self
        slot.mods = Mods.NONE
        slot.status = SlotStatus.NOTREADY

        if match.host == self.id:
            slot.host = True

        if self.match.chat not in services.channels:
            services.channels.add(channel=self.match.chat)

        self.match.chat.connect(self)

        self.match.connected.append(self)

        self.enqueue(writer.match_join(self.match))

        services.logger.info(f"{self.username} joined {match}")
        self.match.enqueue_state(lobby=True)

    def leave_match(self) -> None:
        """``leave_match()`` leaves the multiplayer match, the user is in."""
        match = self.match

        if not match or not (slot := match.find_user(self)):
            return

        match.chat.disconnect(self)
        match.connected.remove(self)
        slot.reset()

        services.logger.info(f"{self.username} left {match}")

        # if that was the last person
        # to leave the multiplayer
        # delete the multi lobby
        if not match.connected:
            services.logger.info(f"{match} is empty! Removing...")
            match.enqueue(writer.match_dispose(match.id), lobby=True)
            services.matches.remove(match)
            return

        if match.host == self.id:
            services.logger.info("Host left, rotating host.")
            for slot in match.slots:
                if not slot.host and slot.status.is_occupied:
                    match.transfer_host(slot)

                    break

        self.match = None

        match.enqueue_state(ignore={self.id}, lobby=True)

    def send(self, message: str, recipent: "Player"):
        recipent.enqueue(
            writer.send_message(
                sender=self.username,
                message=message,
                channel=recipent.username,
                id=self.id,
            )
        )

    async def get_clan_tag(self) -> None:
        clan_tag = await services.database.fetch_one(
            "SELECT c.tag FROM clans c "
            "INNER JOIN users u ON c.id = u.clan_id "
            "WHERE u.id = :user_id",
            {"user_id": self.id},
        )

        if not clan_tag:
            self.username_with_tag = self.username
            return

        self.username_with_tag = f"[{clan_tag["tag"]}] {self.username}"

    async def get_achievements(self) -> None:
        achievements = await services.database.fetch_all(
            "SELECT achievement_id, mode, gamemode FROM users_achievements "
            "WHERE user_id = :user_id",
            {"user_id": self.id},
        )

        for achievement in achievements:
            if not (
                ach := services.get_achievement_by_id(achievement["achievement_id"])
            ):
                services.logger.critical(
                    f"user_achievements: Failed to fetch achievements (id: {achievement['achievement_id']})"
                )
                return

            gamemode = Gamemode(achievement["gamemode"])
            mode = Mode(achievement["mode"])
            user_achievement = UserAchievement(
                **ach.__dict__, gamemode=gamemode, mode=mode
            )

            self.achievements.append(user_achievement)

    async def get_friends(self) -> None:
        friends = await services.database.fetch_all(
            "SELECT user_id2 as id FROM friends WHERE user_id1 = :user_id",
            {"user_id": self.id},
        )

        for friend in friends:
            self.friends.add(friend["id"])

    async def handle_friend(self, user_id: int) -> None:
        if not (target := await services.players.get_offline(user_id)):
            services.logger.critical(
                f"{self.username} tried to change friendship status "
                f"with {user_id}, but no user with that id exists."
            )
            return  # user doesn't exist

        # remove friend
        if await services.database.fetch_one(
            "SELECT 1 FROM friends WHERE user_id1 = :user_id1 AND user_id2 = :user_id2",
            {"user_id": self.id, "user_id2": user_id},
        ):
            await services.database.execute(
                "DELETE FROM friends WHERE user_id1 = :user_id AND user_id2 = :user_id2",
                {"user_id": self.id, "user_id2": user_id},
            )
            self.friends.remove(user_id)

            services.logger.info(
                f"{self.username} removed {target.username} as friends."
            )
            return

        # add friend
        await services.database.execute(
            "INSERT INTO friends (user_id1, user_id2) " "VALUES (:user_id1, :user_id2)",
            {"user_id": self.id, "user_id2": user_id},
        )
        self.friends.add(user_id)

        services.logger.info(f"{self.username} added {target.username} as friends.")

    async def restrict(self) -> None:
        if self.is_restricted:
            return  # just ignore if the user is already restricted.

        self.privileges -= Privileges.VERIFIED

        await services.database.execute(
            "UPDATE users SET privileges -= 4 WHERE id = :user_id", {"user_id": self.id}
        )

        # remove player from leaderboards
        for gamemode in Gamemode:
            for mode in Mode:
                await services.redis.zrem(
                    f"ragnarok:leaderboard:{gamemode.name.lower()}:{mode.value}",
                    self.id,
                )

                # country rank
                await services.redis.zrem(
                    f"ragnarok:leaderboard:{gamemode.name.lower()}:{self.country}:{mode.value}",
                    self.id,
                )

        services.bot.send("Your account has been put in restricted mode!", self)

        services.logger.info(f"{self.username} has been put in restricted mode!")

    async def update_stats(self, score: "Score") -> None:
        mode = ("std", "taiko", "catch", "mania")[score.mode]
        self.update_level()

        await services.database.execute(
            f"UPDATE {score.gamemode.to_db} SET pp_{mode} = :pp, playcount_{mode} = :playcount, "
            f"accuracy_{mode} = :accuracy, total_score_{mode} = :total_score, total_hits_{mode} = :total_hits, "
            f"ranked_score_{mode} = :ranked_score, level_{mode} = :level, playtime_{mode} = playtime_{mode} + :playtime, "
            f"max_combo_{mode} = IF(max_combo_{mode} < :max_combo, :max_combo, max_combo_{mode}) WHERE id = :user_id",
            {
                "pp": self.pp,
                "playcount": self.playcount,
                "accuracy": round(self.accuracy, 2),
                "total_score": self.total_score,
                "total_hits": self.total_hits,
                "ranked_score": self.ranked_score,
                "level": self.level,
                "playtime": score.playtime,
                "max_combo": score.max_combo,
                "user_id": self.id,
            },
        )

    def update_level(self):
        # TODO: relax score
        # required score for lvl 100.
        if self.total_score > 26_931_190_828.629:
            # > lvl 100
            self.level = math.floor(
                (self.total_score - 26_931_190_827 + 9_999_999_999_900) / 99_999_999_999
            )
        else:
            # < 100
            for idx, req_score in enumerate(levels):
                if req_score < self.total_score < levels[idx + 1]:
                    self.level = idx + 1

    # used for background tasks
    async def check_loc(self):
        location = await self.set_location(get=True)

        if not location:
            return

        longitude, latitude, country, country_code = location

        if longitude != self.longitude:
            self.longitude = longitude

        if latitude != self.latitude:
            self.latitude = latitude

        if country_code != self.country_code:
            self.country_code = country_code

        if country != self.country:
            self.country = country

        await self.save_location()

    async def set_location(self, get: bool = False) -> tuple[Any, ...] | None:
        response = await services.http_client_session.get(
            f"http://ip-api.com/json/{self.ip}?fields=status,message,countryCode,region,lat,lon"
        )

        if not (decoded := await response.json()):
            return

        if decoded["status"] == "fail":
            services.logger.critical(
                f"Unable to get {self.username}'s location. Response: {decoded['message']}"
            )
            return

        if not get:
            self.latitude = decoded["lat"]
            self.longitude = decoded["lon"]
            self.country = decoded["countryCode"]
            self.country_code = country_codes[decoded["countryCode"]]

            return

        return (
            decoded["lat"],
            decoded["lon"],
            decoded["countryCode"],
            country_codes[decoded["countryCode"]],
        )

    async def save_location(self):
        await services.database.execute(
            "UPDATE users SET lon = :lon, lat = :lat, country = :country WHERE id = :user_id",
            {
                "lon": self.longitude,
                "lat": self.latitude,
                "country": self.country,
                "user_id": self.id,
            },
        )

    async def get_stats(
        self, gamemode: Gamemode = Gamemode.VANILLA, mode: Mode = Mode.OSU
    ) -> dict[str, Any] | None:
        _stats = await services.database.fetch_one(
            f"SELECT {mode.to_db("ranked_score")}, {mode.to_db("total_score")}, "
            f"{mode.to_db("accuracy")}, {mode.to_db("playcount")}, {mode.to_db("pp")}, "
            f"{mode.to_db("level")}, {mode.to_db("total_hits")}, {mode.to_db("max_combo")} "
            f"FROM {gamemode.to_db} WHERE id = :user_id",
            {"user_id": self.id},
        )

        if not _stats:
            return

        stats = dict(_stats)

        stats["rank"] = await self.get_rank(gamemode, mode)
        stats["country_rank"] = await self.get_country_rank(gamemode, mode)

        return stats

    async def get_rank(
        self, gamemode: Gamemode = Gamemode.VANILLA, mode: Mode = Mode.OSU
    ) -> int:
        rank: int = await services.redis.zrevrank(
            f"ragnarok:leaderboard:{gamemode.name.lower()}:{mode}",
            str(self.id),
        )
        return rank + 1 if rank is not None else 0

    async def get_country_rank(
        self, gamemode: Gamemode = Gamemode.VANILLA, mode: Mode = Mode.OSU
    ) -> int:
        rank: int = await services.redis.zrevrank(
            f"ragnarok:leaderboard:{gamemode.name.lower()}:{self.country}:{mode}",
            str(self.id),
        )
        return rank + 1 if rank is not None else 0

    async def update_rank(
        self, gamemode: Gamemode = Gamemode.VANILLA, mode: Mode = Mode.OSU
    ) -> int:
        if not self.is_restricted:
            await services.redis.zadd(
                f"ragnarok:leaderboard:{gamemode.name.lower()}:{mode}",
                {str(self.id): self.pp},
            )

            # country rank
            await services.redis.zadd(
                f"ragnarok:leaderboard:{gamemode.name.lower()}:{self.country}:{mode}",
                {str(self.id): self.pp},
            )

        return await self.get_rank(gamemode, mode)

    async def update_stats_cache(self) -> bool:
        stats = await self.get_stats(self.gamemode, self.play_mode)

        if not stats:
            return False

        self.ranked_score = stats["ranked_score"]
        self.accuracy = stats["accuracy"]
        self.playcount = stats["playcount"]
        self.total_score = stats["total_score"]
        self.level = stats["level"]
        self.rank = stats["rank"]
        self.pp = math.ceil(stats["pp"])
        self.total_hits = stats["total_hits"]
        self.max_combo = stats["max_combo"]

        return True

    async def report(self, target: "Player", reason: str) -> None:
        await services.database.execute(
            "INSERT INTO reports (reporter, reported, reason) "
            "VALUES (:user_id, :target_id, :reason)",
            {"user_id": self.id, "target_id": target.id, "reason": reason},
        )

    async def log(self, note: str, type: LoggingType = LoggingType.ANY) -> None:
        await services.database.execute(
            "INSERT INTO logs (user_id, note, type) " "VALUES (:user_id, :note, :type)",
            {"user_id": self.id, "note": note, "type": type},
        )

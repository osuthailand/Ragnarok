from typing import TYPE_CHECKING

from objects import services
from packets import writer


if TYPE_CHECKING:
    from objects.player import Player


class Channel:
    def __init__(self, **kwargs):
        self.name: str = kwargs.get("name", "#unnamed")  # real name. fx #multi_1

        self.display_name: str = kwargs.get("display_name", self.name)  # display name

        self.description: str = kwargs.get("description", "An osu! channel.")

        self.is_public: bool = kwargs.get("public", True)
        self.is_read_only: bool = kwargs.get("read_only", False)
        self.is_auto_join: bool = kwargs.get("auto_join", False)

        self.is_staff: bool = kwargs.get("staff", False)
        self.is_temporary: bool = kwargs.get(
            "is_temporary", False
        )  # object will get removed upon no connection

        self.connected: list["Player"] = []

    @property
    def is_dm(self) -> bool:
        return self.display_name[0] != "#"

    @property
    def is_multiplayer(self) -> bool:
        return self.display_name == "#multiplayer"

    def enqueue(self, data: bytes, ignore: tuple = ()) -> None:
        for player in self.connected:
            if player.id not in ignore:
                player.enqueue(data)

    def update_info(self) -> None:
        if self.is_temporary:
            for player in self.connected:
                player.enqueue(writer.channel_info(self))
        else:
            services.players.enqueue(writer.channel_info(self))

    def connect(self, player: "Player"):
        if self in player.channels:
            services.logger.critical(
                f"{player.username} tried to joined {self.name}, which they're already connected to."
            )
            return

        # if the player is not a staff and tries to join
        # a staff channel, it'll return false.
        if not player.is_staff and self.is_staff:
            services.logger.critical(
                f"{player.username} tried to join {self.name} with insufficient privileges."
            )
            return

        self.connected.append(player)
        player.channels.append(self)

        player.enqueue(writer.channel_join(self.display_name))
        self.update_info()

        services.logger.info(f"{player.username} joined {self.name}")

    def disconnect(self, player: "Player"):
        if self not in player.channels:
            services.logger.critical(
                f"{player.username} tried to leave {self.name}, which they aren't connected to."
            )
            return

        self.connected.remove(player)
        player.channels.remove(self)

        player.enqueue(writer.channel_kick(self.display_name))

        if self.is_temporary and not self.connected:
            services.channels.remove(self)

        self.update_info()

        services.logger.info(f"{player.username} parted from {self.name}")

    def send(self, message: str, sender: "Player") -> None:
        if not sender.is_bot:
            if not (self in sender.channels or self.is_read_only):
                return

        ret = writer.send_message(
            sender=sender.username,
            message=message,
            channel=self.display_name,
            id=sender.id,
        )

        self.enqueue(ret, ignore=(sender.id,))

        services.logger.info(f"<{sender.username}> {message} [{self.name}]")

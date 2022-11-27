from objects.channel import Channel
from objects.player import Player
from objects import services
from typing import Optional


class Group(Channel):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.owner: Player = kwargs.get("owner", None)  # type: ignore

    @classmethod
    async def create(
        cls, owner: Player, name: str, description: Optional[str] = None
    ) -> "Group":
        kwargs = {
            "owner": owner,
            "name": f"#{name}",
            "description": f"Group created by {owner.username}"
            if not description
            else description,
            "raw": f"#group_{name}",
        }
        c = cls(**kwargs)
        await owner.join_channel(c)
        services.channels.channels.append(c)
        await c.update_info()
        return c

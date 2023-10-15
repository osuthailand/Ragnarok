import os

from starlette.requests import Request
from starlette.responses import FileResponse
from starlette.routing import Router


avatar = Router()
a_path = ".data/avatars/"


@avatar.route("/{uid}")
async def handle(req: Request) -> FileResponse:
    uid = req.path_params["uid"]

    # quick fix, before we make a website for the server
    if uid == "osu_menu_icon":
        return FileResponse(
            path=a_path + "osu_menu_icon.gif"
        )

    has_avatar = os.path.exists(a_path + f"{uid}.png")
    return FileResponse(
        path=a_path+f"{uid if has_avatar else '0'}.png"
    )

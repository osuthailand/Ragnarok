import os

from starlette.requests import Request
from starlette.responses import FileResponse
from starlette.routing import Router


avatar = Router()
a_path = ".data/avatars/"


@avatar.route("/{uid:int}")
async def handle(req: Request) -> bytes:
    uid = req.path_params["uid"]
    has_avatar = os.path.exists(a_path + f"{uid}.png")
    return FileResponse(
        path=a_path+f"{uid if has_avatar else '0'}.png"
    )

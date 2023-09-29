from typing import Any
import orjson

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Router
from utils.general import ORJSONResponse

api = Router()

@api.route("/")
async def dash(req: Request) -> JSONResponse: 
    return ORJSONResponse(
        content={
            "motd": "din mor"
        }
    )
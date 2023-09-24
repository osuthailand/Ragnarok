from typing import Any
import orjson

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Router

api = Router()

class ORJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return orjson.dumps(content)

@api.route("/")
async def dash(req: Request) -> JSONResponse: 
    return ORJSONResponse(
        content={
            "motd": "din mor"
        }
    )
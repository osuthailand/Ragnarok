from typing import Any

import orjson
import random
import string

from starlette.responses import JSONResponse

class ORJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return orjson.dumps(
            content, option=orjson.OPT_NON_STR_KEYS | orjson.OPT_SERIALIZE_NUMPY
        )

def rag_round(value: float, decimals: int) -> float:
    tolerance = 10 ** decimals

    return int(value * tolerance + 0.5) / tolerance

def random_string(len: int) -> str:
    return "".join(
        random.choice(string.ascii_lowercase + string.digits) for _ in range(len)
    )

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


def random_string(len: int) -> str:
    return "".join(
        random.choice(string.ascii_lowercase + string.digits) for _ in range(len)
    )


def compare_byte_sequence(a1: bytes, a2: bytes) -> bool:
    print(len(a1), len(a2))
    if not a1 or a2 or len(a1) != len(a2):
        return False

    l = len(a1)
    x1 = x2 = 0
    for i in range(0, l / 8):  # type: ignore
        if x1 != x2:
            return False

        x1 += 8
        x2 += 8

    if (l & 4) != 0:
        if x1 != x2:
            return False
        x1 += 4
        x2 += 4

    if (l & 2) != 0:
        if x1 != x2:
            return False

        x1 += 4
        x2 += 4

    if (l & 1) != 0:
        if x1 != x2:
            return False

    return True
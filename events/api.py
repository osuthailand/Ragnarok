import types
from typing import Any, Callable
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Router
from constants.playmode import Mode
from objects import services
from objects.beatmap import Beatmap
from utils import log
from utils.general import ORJSONResponse
from starlette import status

from functools import wraps

api = Router()


def error(code: int, reason: str) -> ORJSONResponse:
    return ORJSONResponse(content={"error": code, "reason": reason}, status_code=code)


def ensure_parameters(**parameters):
    """`ensure_parameters(**parameters)` checks all the parameters
    given in the query, and if any of them matchs the
    optional parameters that are set by the function
    it'll get converted to its respective type and
    put as an argument in the function"""

    def decorator(cb: Callable) -> Callable:
        @wraps(cb)
        async def wrapper(req: Request, *args, **kwargs):
            additional_args = {}
            for key, class_type in parameters.items():
                # when the class type is union, it means its an optional
                # eg. parameter=Any | None
                is_optional = type(class_type) == types.UnionType
                if key not in req.query_params:
                    # if the key is optional, it shouldn't alert user
                    if is_optional:
                        continue
                    else:
                        return error(400, "Missing required parameters")

                arg = req.query_params[key]

                try:
                    # fix for mode and mods (+ bool)
                    if arg.isdecimal():
                        arg = int(arg)
                    if is_optional:
                        # weird way of getting the first type
                        arg = class_type.__args__[0](arg)
                    else:
                        arg = class_type(arg)

                except:
                    return error(
                        400, f"There is something incorrect about query parameter {key}"
                    )

                additional_args[key] = arg

            return await cb(req, *args, **additional_args, **kwargs)

        return wrapper

    return decorator


@api.route("/")
async def dash(req: Request) -> JSONResponse:
    return ORJSONResponse(content={"motd": "din mor"})


@api.route("/leaderboard")
@ensure_parameters(
    country=str | None,
    mode=Mode | None,
    relax=bool | None,
    page=int | None,
    order=str | None,
)
async def leaderboard(
    req: Request,
    /,
    country: str = "XX",
    mode: Mode = Mode.OSU,
    relax: bool = False,
    page: int = 1,
    order: str = "pp",
) -> JSONResponse:
    if page <= 0:
        page = 1

    if order not in (
        "pp",
        "ranked_score",
        "total_score",
        "accuracy",
        "level",
        "playcount",
    ):
        return error(400, "Invalid `order` value")

    table = "stats_rx" if relax else "stats"

    query = (
        f"SELECT us.id, us.{mode.to_db('pp')}, us.{mode.to_db('ranked_score')}, "
        f"us.{mode.to_db('total_score')}, us.{mode.to_db('accuracy')}, us.{mode.to_db('level')}, "
        f"us.{mode.to_db('playcount')}, u.username, u.country FROM {table} us "
        "JOIN users u ON u.id = us.id WHERE u.privileges & 4 "
    )

    if country != "XX":
        query += f"AND u.country = '{country}' "

    query += f"ORDER BY {order} DESC LIMIT 50 OFFSET {(page - 1) * 50}"

    leaderboard = await services.sql.fetchall(query, _dict=True)

    return ORJSONResponse(content={"data": leaderboard})


@api.route("/get_profile_stats")
@ensure_parameters(
    id=int,
    mode=Mode | None,
    relax=bool | None,
)
async def get_profile_stats(
    req: Request, /, id: int, mode: Mode = Mode.OSU, relax: bool = False
) -> ORJSONResponse:
    # get_offline always checks cache first
    p = await services.players.get_offline(id)

    if not p:
        return error(400, f"No player with the id {id} was found.")

    stats = await p.get_stats(relax, mode)

    # players who is already in the cache
    # already has achievements cached.
    if not p.achievements:
        await p.get_achievements()

    profile_data = {
        "username": p.username,
        "safe_username": p.safe_name,
        "country": p.country,
        "privileges": p.privileges,
        "badges": [],  # TODO: this
        "achievements": [x.__dict__() for x in p.achievements],
    }

    return ORJSONResponse(content={"data": {"profile": profile_data, "stats": stats}})


@api.route("/get_beatmap")
@ensure_parameters(bid=int)
async def get_beatmap(req: Request, /, bid: int) -> ORJSONResponse:
    bmap = await services.beatmaps.get_by_map_id(bid)

    if not bmap:
        return error(204, f"No beatmap with map id {bid} found")

    # temp
    data = {
        "map_id": bid,
        "set_id": bmap.set_id,
        "map_md5": bmap.map_md5,
        "title": bmap.title,
        "artist": bmap.artist,
        "version": bmap.version,
        "stars": bmap.stars,
        "od": bmap.od,
        "ar": bmap.ar,
        "cs": bmap.cs,
        "hp": bmap.hp,
        "passes": bmap.passes,
        "plays": bmap.plays,
        "hit_length": bmap.hit_length,
        "mode": bmap.mode,
        "bpm": bmap.bpm,
        "approved": bmap.approved,
    }

    return ORJSONResponse(content={"data": data})


@api.route("/get_beatmapset")
@ensure_parameters(sid=int)
async def get_beatmapset(req: Request, /, sid: int) -> ORJSONResponse:
    bmap = await services.beatmaps.get_by_set_id(sid)

    if not bmap:
        return error(204, f"No beatmap with map id {sid} found")

    data = {
        "map_id": bid,
        "set_id": bmap.set_id,
        "map_md5": bmap.map_md5,
        "title": bmap.title,
        "artist": bmap.artist,
        "version": bmap.version,
        "stars": bmap.stars,
        "od": bmap.od,
        "ar": bmap.ar,
        "cs": bmap.cs,
        "hp": bmap.hp,
        "passes": bmap.passes,
        "plays": bmap.plays,
        "hit_length": bmap.hit_length,
        "mode": bmap.mode,
        "bpm": bmap.bpm,
        "approved": bmap.approved,
    }

    return ORJSONResponse(content={"data": data})


@api.route("/get_beatmap_scores")
@ensure_parameters(bid=int)
async def get_beatmapset(req: Request, /, bid: int) -> ORJSONResponse:
    return error(501, "Not implemented")

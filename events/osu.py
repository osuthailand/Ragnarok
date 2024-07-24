from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import IntEnum, unique
import os
import math
import copy
from pathlib import Path
import time
import bcrypt
import hashlib
import aiofiles
import numpy as np
from constants.playmode import Gamemode
from objects.achievement import UserAchievement
from packets import writer


from utils import general
from functools import wraps
from objects import services
from collections import defaultdict
from typing import Callable

from objects.player import Player
from constants.mods import Mods
from constants.playmode import Mode  # this is being used for achievements condition
from urllib.parse import unquote
from objects.beatmap import Beatmap
from starlette.routing import Router
from starlette.requests import Request
from constants.player import Privileges
from objects.score import Score, SubmitStatus
from starlette.responses import FileResponse, Response, RedirectResponse
from starlette import status


def check_auth(
    username_param: str,
    password_param: str,
    # cho_auth: bool = False,
    response: bytes | None = None,
    method="GET",
):
    def decorator(cb: Callable) -> Callable:
        @wraps(cb)
        async def wrapper(request: Request, *args, **kwargs):
            if method == "GET":
                if (
                    username_param not in request.query_params
                    or password_param not in request.query_params
                ):
                    return Response(content=response or b"not allowed")

                player = unquote(request.query_params[username_param])
                password = request.query_params[password_param]
            else:
                form = await request.form()

                if username_param not in form or password_param not in form:
                    return Response(content=response or b"not allowed")

                player = unquote(str(form[username_param]))
                password = str(form[password_param])

            if not (player := services.players.get(player)):
                return Response(content=response or b"not allowed")

            if player.passhash in services.bcrypt_cache:
                if password.encode("utf-8") != services.bcrypt_cache[player.passhash]:
                    return Response(content=response or b"not allowed")

            return await cb(request, player, *args, **kwargs)

        return wrapper

    return decorator


osu = Router()


@osu.route("/users", methods=["POST"])
async def registration(request: Request) -> Response:
    form = await request.form()
    username = str(form["user[username]"])
    email = str(form["user[user_email]"])
    password = str(form["user[password]"])

    error_response = defaultdict(list)

    if await services.database.fetch_one(
        "SELECT 1 FROM users WHERE username = :username", {"username": username}
    ):
        error_response["username"].append(
            "A user with that name already exists in our database."
        )

    if await services.database.fetch_one(
        "SELECT 1 FROM users WHERE email = :email", {"email": email}
    ):
        error_response["user_email"].append(
            "A user with that email already exists in our database."
        )

    if error_response:
        return general.ORJSONResponse(
            status_code=400, content={"form_error": {"user": error_response}}
        )

    if not services.osu_settings.allow_ingame_registration.value:
        # osu! will attempt to go to https://url?username={username}&email={email}
        return general.ORJSONResponse(
            status_code=403,
            content={
                "error": "Please register from Rina website",
                "url": f"https://{services.domain}/register",
            },
        )

    if form["check"] == "0":
        password_md5 = hashlib.md5(password.encode()).hexdigest().encode()
        password_hash = bcrypt.hashpw(password_md5, bcrypt.gensalt())

        id = await services.database.execute(
            "INSERT INTO users (username, safe_username, passhash, "
            "email, privileges, latest_activity_time, registered_time) "
            "VALUES (:username, :safe_username, :passhash, :email, :privileges, UNIX_TIMESTAMP(), UNIX_TIMESTAMP())",
            {
                "username": username,
                "safe_username": username.lower().replace(" ", "_"),
                "passhash": password_hash,
                "email": email,
                "privileges": Privileges.PENDING.value,
            },
        )

        await services.database.execute(
            "INSERT INTO stats (id) VALUES (:user_id)", {"user_id": id}
        )
        await services.database.execute(
            "INSERT INTO stats_rx (id) VALUES (:user_id)", {"user_id": id}
        )

    return Response(content=b"ok")


@dataclass
class DotOsuEndpoint:
    name: str
    endpoint: str
    ratelimit_pause: datetime | None = None
    corrected_files: int = 0


BANCHO_OSU_ENDPOINT = DotOsuEndpoint(
    name="bancho",
    endpoint="https://osu.ppy.sh/web/osu-getosufile.php?q={map_id}",
)
MINO_OSU_ENDPOINT = DotOsuEndpoint(
    name="mino",
    endpoint="https://catboy.best/osu/{map_id}?raw=1",
)
MIRROR_ORDER = (BANCHO_OSU_ENDPOINT, MINO_OSU_ENDPOINT)

BEATMAPS_DIRECTORY = Path(".data/beatmaps")


async def save_beatmap_file(map_id: int) -> None | Response:
    """
    `save_beatmap_file(map_id: int)` saves a beatmaps .osu file to the beatmaps directory
    in .data. It priorities to use bancho's .osu endpoint, as it's the most accurate and
    up to date, but sometimes we hit ratelimit and therefore we should use other mirrors.
    Currently the only other mirror is Mino.
    """
    dot_osu = BEATMAPS_DIRECTORY / f"{map_id}.osu"

    if dot_osu.exists():
        return

    if all(host.ratelimit_pause is not None for host in MIRROR_ORDER):
        services.logger.critical("Both bancho and mino has hit ratelimit.")

    with dot_osu.open("w+") as osu:
        for host in MIRROR_ORDER:
            elapsed_start = time.time_ns()

            if host.ratelimit_pause and host.ratelimit_pause > datetime.now():
                continue

            if host.ratelimit_pause and host.ratelimit_pause < datetime.now():
                services.logger.info(f"{host.name}: ratelimited reset")
                host.ratelimit_pause = None

            response = await services.http_client_session.get(
                host.endpoint.format(map_id=map_id)
            )

            # if the response is 459, it should start ratelimit pause and use the next endpoint
            if response.status == 459:
                if host.name == "bancho":
                    host.ratelimit_pause = datetime.now() + timedelta(minutes=5)
                else:
                    host.ratelimit_pause = datetime.now() + timedelta(
                        minutes=1, seconds=30
                    )

                services.logger.info(
                    f"{host.name}: reached ratelimit and will continue to the other mirror."
                )
                continue

            # even if the map doesn't exist on bancho, it'll still return 200
            # therefore we need to check if the response text is empty.
            if host.name == "bancho" and response.status == 200:
                decoded = await response.text()
                if decoded == "":
                    services.logger.warning(
                        f"{host.name}: beatmap {map_id} doesn't exist on the official server, checking mirror."
                    )
                    continue

            if host.name == "mino":
                # mino does handle it correctly and returns 404 if the beatmap doesn't exist.
                # but we'll also want to check for other statuses.
                if response.status != 200:
                    decoded = await response.json()
                    services.logger.warning(
                        f"{host.name}: beatmap {map_id}.osu returned error: {decoded["error"]}"
                    )
                    continue

                # use x-ratelimit-remaining to start ratelimit before 459 and save
                # our ip from getting automatically banned.
                ratelimit_remaining = response.headers["x-ratelimit-remaining"]

                if ratelimit_remaining == 1:
                    host.ratelimit_pause = datetime.now() + timedelta(
                        minutes=1, seconds=30
                    )
                    continue

            decoded = await response.text()

            if "nginx" in decoded:
                services.logger.error(
                    f"Unhandled .osu response through {host.name}: (code {response.status})"
                )
                services.logger.error(decoded)
                continue

            osu.write(decoded)

            elapsed = (time.time_ns() - elapsed_start) // 1e6
            services.logger.info(
                f"Successfully saved {map_id}.osu through {host.name} - elapsed {elapsed}ms"
            )
            break


# @osu.route("/web/bancho_connect.php")
# @check_auth("u", "h", cho_auth = True)
# async def bancho_connect(req: Request) -> Response:
#     # TODO: make some verification (ch means client hash)
#     #       "error: verify" is a thing
#     return Response(content=req.headers["CF-IPCountry"].lower().encode())


SCORES_FORMAT = (
    "{id_}|{username}|{score}|"
    "{max_combo}|{count_50}|{count_100}|{count_300}|{count_miss}|"
    "{count_katu}|{count_geki}|{perfect}|{mods}|{user_id}|"
    "{position}|{submitted}|1"
)


@unique
class LeaderboardType(IntEnum):
    LOCAL = 0
    TOP = 1
    MODS = 2
    FRIENDS = 3
    COUNTRY = 4


@osu.route("/web/osu-osz2-getscores.php")
@check_auth("us", "ha")
async def get_scores(request: Request, player: Player) -> Response:
    await player.update_latest_activity()

    map_md5 = request.query_params["c"]
    filename = request.query_params["f"]
    set_id = int(request.query_params["i"])

    if not (map := await services.beatmaps.get(map_md5)):
        map_set = await Beatmap.get_from_osu_api(set_id=set_id)

        if type(map_set) != list:
            return Response(content=b"-1|false")

        if not map_set:
            services.logger.critical(
                f"<md5={map_md5} set_id={set_id}> could not be found in osu!'s api."
            )
            return Response(content=b"-1|false")

        map = None

        for map_child in map_set:
            if map_child.filename == filename:
                map = map_child

        if not map:
            services.logger.critical(
                f"<md5={map_md5} set_id={set_id}> failed to find difficulty through filename. (difficulty most likely deleted or renamed)"
            )
            return Response(content=b"-1|false")

        if map.map_md5 != map_md5:
            services.logger.debug(
                f"<md5={map_md5} set_id={set_id}> is need of an update!"
            )
            return Response(content=b"1|false")

        return Response(content=b"-1|false")

    # don't cache maps that doesn't have leaderboard
    if not map.approved.has_leaderboard:
        services.beatmaps.remove(map.map_md5)

        return Response(content=f"{map.approved.to_osu}|false".encode())

    mods = int(request.query_params["mods"])

    # switch user to the respective gamemode based on leaderboard mods.
    prev_gamemode = player.gamemode
    player.gamemode = Gamemode.RELAX if mods & Mods.RELAX else Gamemode.VANILLA

    # enqueue respective stats if gamemode has changed
    if prev_gamemode != player.gamemode:
        await player.update_stats_cache()
        services.players.enqueue(writer.update_stats(player))

    response = [map.web_format]

    mode = int(request.query_params["m"])

    query = (
        "SELECT s.id as id_, COALESCE(CONCAT('[', c.tag, '] ', u.username), u.username) as username, "
        "s.max_combo, s.count_50, s.count_100, s.count_300, s.count_miss, s.count_katu, "
        f"CAST(s.{player.gamemode.score_order} as INT) as score, s.submitted, s.count_geki, s.perfect, "
        "s.mods, s.user_id, u.country FROM scores s INNER JOIN users u ON u.id = s.user_id "
        "LEFT JOIN clans c ON c.id = u.clan_id WHERE s.map_md5 = :map_md5 AND s.mode = :mode "
        "AND s.status = 3 AND u.privileges & 4 AND s.gamemode = :gamemode "
    )
    params = {"map_md5": map.map_md5, "mode": mode, "gamemode": player.gamemode.value}

    leaderboard_type = LeaderboardType(int(request.query_params["v"]))

    match leaderboard_type:
        case LeaderboardType.MODS:
            query += "AND mods = :mods "
            params["mods"] = mods
        case LeaderboardType.COUNTRY:
            query += "AND u.country = :country "
            params["country"] = player.country
        case LeaderboardType.FRIENDS:
            query += "AND s.user_id IN :friends "
            params["friends"] = player.friends

    query += f"ORDER BY score DESC, s.submitted ASC LIMIT 50"

    personal_best = await services.database.fetch_one(
        f"SELECT s.id as id_, CAST(s.{player.gamemode.score_order} as INT) as score, "
        "s.max_combo, s.count_50, s.count_100, s.count_300, s.count_miss, s.count_katu, "
        "s.count_geki, s.perfect, s.mods, s.submitted FROM scores s WHERE s.status = 3 "
        "AND s.map_md5 = :map_md5 AND s.gamemode = :gamemode AND s.mode = :mode "
        "AND s.user_id = :user_id LIMIT 1",
        {
            "map_md5": map.map_md5,
            "gamemode": player.gamemode.value,
            "mode": mode,
            "user_id": player.id,
        },
    )

    if not personal_best:
        response.append("")
    else:
        position = await services.database.fetch_val(
            "SELECT COUNT(*) FROM scores s "
            "INNER JOIN beatmaps b ON b.map_md5 = s.map_md5 "
            "INNER JOIN users u ON u.id = s.user_id "
            f"WHERE s.{player.gamemode.score_order} > :pb_score "
            "AND s.gamemode = :gamemode AND s.map_md5 = :map_md5 "
            "AND u.privileges & 4 AND s.status = 3 "
            "AND s.mode = :mode",
            {
                "pb_score": personal_best["score"],
                "gamemode": player.gamemode.value,
                "map_md5": map.map_md5,
                "mode": mode,
            },
        )

        if position is not None:
            response.append(
                SCORES_FORMAT.format(
                    **dict(personal_best),
                    user_id=player.id,
                    username=player.username_with_tag,
                    position=position + 1,
                )
            )

    top_scores = await services.database.fetch_all(query, params)

    response.extend(
        [
            SCORES_FORMAT.format(**dict(score), position=idx + 1)
            for idx, score in enumerate(top_scores)
        ]
    )

    services.loop.create_task(save_beatmap_file(map.map_id))

    return Response(content="\n".join(response).encode())


@osu.route("/web/maps/{filename:str}")
async def get_map_file(request: Request) -> RedirectResponse:
    filename = request.path_params["filename"]
    return RedirectResponse(
        f"https://osu.ppy.sh/web/maps/{filename}",
        status_code=status.HTTP_301_MOVED_PERMANENTLY,
    )


@osu.route("/web/osu-submit-modular-selector.php", methods=["POST"])
async def score_submission(request: Request) -> Response:
    # possible errors in osu! score submission system:

    # version mismatch: osu! version in form and score data is mismatched
    # reset: password reset
    # pass: wrong password
    # verify: account verify needed
    # nouser: username is wrong
    # inactive/ban: account hasnt been activated or banned
    # beatmap: beatmap is not existed/not ranked in beatmap table
    # disabled: mods not allowed to submit
    # oldver: old version
    # unknown: user is invalid or just for any exception
    # missinginfo: not all fields are there
    # checksum: score verification failed
    # dup: duplicated score in 24 hours period
    # invalid: score is impossible/hacked
    # no: ignore the score
    form = await request.form()

    if not form:
        return Response(content=b"error: missinginfo")

    submission_key = f"osu!-scoreburgr---------{form["osuver"]}"
    score = await Score.from_submission(
        form.getlist("score")[0],  # type: ignore
        form["iv"],  # type: ignore
        submission_key,
        int(form["x"]),  # type: ignore
    )

    if not score or not score.player or not score.map or score.player.is_restricted:
        return Response(content=b"error: beatmap")

    await score.player.update_latest_activity()

    if not score.player.privileges & Privileges.VERIFIED:
        return Response(content=b"error: verify")

    if score.mods & Mods.DISABLED:
        return Response(content=b"error: disabled")

    passed = score.status >= SubmitStatus.PASSED

    # get current first place holder, if any
    first_place_holder = await services.database.fetch_val(
        "SELECT s.user_id FROM scores s INNER JOIN users u ON u.id = s.user_id "
        "WHERE s.map_md5 = :map_md5 AND s.mode = :mode AND s.gamemode = :gamemode "
        " AND u.privileges & 4 ORDER BY s.pp DESC LIMIT 1",
        {"map_md5": score.map.map_md5, "mode": score.mode, "gamemode": score.gamemode},
    )

    score.playtime = int(form["st" if passed else "ft"]) // 1000  # type: ignore
    score.id = await score.save_to_db()

    score.map.plays += 1

    await services.database.execute(
        "UPDATE beatmaps SET plays = plays + 1 WHERE map_md5 = :map_md5",
        {"map_md5": score.map.map_md5},
    )

    # check if the beatmap playcount for player exists first
    # if it does, we just wanna update.
    if beatmap_playcount := await services.database.fetch_val(
        "SELECT id FROM beatmap_playcount WHERE map_md5 = :map_md5 "
        "AND user_id = :user_id AND mode = :mode AND gamemode = :gamemode",
        {
            "map_md5": score.map.map_md5,
            "user_id": score.player.id,
            "mode": score.mode,
            "gamemode": score.gamemode,
        },
    ):
        await services.database.execute(
            "UPDATE beatmap_playcount SET playcount = playcount + 1 WHERE id = :id ",
            {"id": beatmap_playcount},
        )
    # else we want to insert
    else:
        await services.database.execute(
            "INSERT INTO beatmap_playcount (map_md5, user_id, mode, gamemode, playcount) "
            "VALUES (:map_md5, :user_id, :mode, :gamemode, 1) ",
            {
                "map_md5": score.map.map_md5,
                "user_id": score.player.id,
                "mode": score.mode,
                "gamemode": score.gamemode,
            },
        )

    if not passed:
        services.logger.info(
            f"{score.player.username} submitted a failed or quitted score on {score.map.full_title} ({score.mode.to_string()}: {score.pp:.2f}pp) {score.gamemode.name}"
        )
        score.player.last_score = score
        return Response(content=b"error: no")

    score.map.passes += 1

    await services.database.execute(
        "UPDATE beatmaps SET passes = passes + 1 WHERE map_md5 = :map_md5",
        {"map_md5": score.map.map_md5},
    )

    stats = score.player

    # check if the user is playing the map for the first time
    prev_stats = None

    if stats.total_score > 0:
        prev_stats = copy.copy(stats)

    # save replay
    with open(f".data/replays/{score.id}.osr", "wb+") as file:
        file.write(await form["score"].read())  # type: ignore

    # restrict the player if they
    # somehow managed to submit a
    # score without a replay.
    if not form.getlist("score"):
        await score.player.restrict()
        return Response(content=b"error: invalid")

    # calculate new stats
    if not score.map.approved.has_leaderboard:
        return Response(content=b"error: no")

    stats.playcount += 1
    stats.total_score += score.score
    stats.total_hits += score.total_hits

    if score.status == SubmitStatus.BEST:
        ranked_score = score.score

        if score.previous_best:
            ranked_score -= score.previous_best.score

        stats.ranked_score += ranked_score

        scores = await services.database.fetch_all(
            "SELECT pp, accuracy, awards_pp FROM scores "
            "WHERE user_id = :user_id AND mode = :mode "
            "AND status = 3 AND gamemode = :gamemode "
            "AND awards_pp = 1 ORDER BY pp DESC LIMIT 100",
            {
                "user_id": stats.id,
                "mode": score.mode.value,
                "gamemode": score.gamemode.value,
            },
        )

        stats.accuracy = np.sum(
            [score["accuracy"] * 0.95**place for place, score in enumerate(scores)]
        )  # type: ignore
        stats.accuracy *= 100 / (20 * (1 - 0.95 ** len(scores)))
        stats.accuracy /= 100

        if score.map.approved.awards_pp:
            weighted_pp = np.sum(
                [score["pp"] * 0.95**position for position, score in enumerate(scores)]
            )  # type: ignore
            weighted_pp += 416.6667 * (1 - 0.9994 ** len(scores))
            stats.pp = math.ceil(weighted_pp)

            stats.rank = await stats.update_rank(score.gamemode, score.mode)

        await stats.update_stats(score)
        services.players.enqueue(writer.update_stats(stats))

        # if the player got first place
        # on the map announce it
        if score.position == 1 and not stats.is_restricted:
            if not (channel := services.channels.get("#announce")):
                return Response(content=b"error: unknown")

            gamemode = "[Relax]" if score.gamemode == Gamemode.RELAX else ""

            channel.send(
                f"{score.player.embed} achieved #{score.position} on {score.map.embed} ({score.mode.to_string()}) {gamemode}",
                sender=services.bot,
            )

            # announce that the previous first place holder
            # lost their rank 1 on this map in their recent activities
            if first_place_holder is not None and first_place_holder != score.player.id:
                await services.database.execute(
                    "INSERT INTO recent_activities (user_id, activity, map_md5, mode, gamemode) "
                    "VALUES (:user_id, :activity, :map_md5, :mode, :gamemode)",
                    {
                        "user_id": first_place_holder,
                        "activity": "lost rank #1 on",
                        "map_md5": score.map.map_md5,
                        "mode": score.mode,
                        "gamemode": score.gamemode,
                    },
                )

            # put it into the new first place holders recent activities.
            await services.database.execute(
                "INSERT INTO recent_activities (user_id, activity, map_md5, mode, gamemode) "
                "VALUES (:user_id, :activity, :map_md5, :mode, :gamemode)",
                {
                    "user_id": score.player.id,
                    "activity": "achieved rank #1 on",
                    "map_md5": score.map.map_md5,
                    "mode": score.mode,
                    "gamemode": score.gamemode,
                },
            )

    # TODO: map difficulty changing mods

    awarded_achievements = []
    for achievement in services.achievements:
        user_achievement = UserAchievement(
            **achievement.__dict__, gamemode=score.gamemode, mode=score.mode
        )

        if user_achievement in stats.achievements:
            continue

        # if the achievement condition matches
        # with the score, it should be unlocked.
        try:
            if eval(achievement.condition):
                services.logger.info(
                    f"{stats.username} unlocked {achievement.name} that has condition: {achievement.condition}"
                )
                await services.database.execute(
                    "INSERT INTO users_achievements (user_id, achievement_id, mode, gamemode) "
                    "VALUES (:user_id, :achievement_id, :mode, :gamemode)",
                    {
                        "user_id": score.player.id,
                        "achievement_id": achievement.id,
                        "mode": score.mode.value,
                        "gamemode": score.gamemode.value,
                    },
                )

                stats.achievements.append(user_achievement)
                awarded_achievements.append(achievement)
        except:
            # usually "failed" conditions are due to `Player.last_score` is none
            continue

    achievements = "/".join(str(achievement) for achievement in awarded_achievements)
    gamemode = "[Relax]" if score.gamemode == Gamemode.RELAX else ""

    services.logger.info(
        f"{stats.username} submitted a score on {score.map.full_title} ({score.mode.to_string()}: {score.pp:.2f}pp) {gamemode}"
    )

    score.player.last_score = score

    # only do charts if the score isn't relax
    # but do charts if the user is playing on rina
    response: list = []
    if score.gamemode != Gamemode.VANILLA and not stats.using_rina:
        return Response(content=b"error: no")

    response.append(
        "|".join(
            (
                f"beatmapId:{score.map.map_id}",
                f"beatmapSetId:{score.map.set_id}",
                f"beatmapPlaycount:{score.map.plays}",
                f"beatmapPasscount:{score.map.passes}",
                f"approvedDate:{score.map.approved_date}",
            )
        )
    )

    response.append(
        "|".join(
            (
                "chartId:beatmap",
                f"chartUrl:{score.map.url}",
                "chartName:Beatmap Ranking",
                *(
                    (
                        Beatmap.add_chart("rank", after=score.position),
                        Beatmap.add_chart("accuracy", after=score.accuracy),
                        Beatmap.add_chart("maxCombo", after=score.max_combo),
                        Beatmap.add_chart("rankedScore", after=score.score),
                        Beatmap.add_chart("totalScore", after=score.score),
                        Beatmap.add_chart("pp", after=math.ceil(score.pp)),
                    )
                    if not score.previous_best
                    else (
                        Beatmap.add_chart(
                            "rank", score.previous_best.position, score.position
                        ),
                        Beatmap.add_chart(
                            "accuracy", score.previous_best.accuracy, score.accuracy
                        ),
                        Beatmap.add_chart(
                            "maxCombo", score.previous_best.max_combo, score.max_combo
                        ),
                        Beatmap.add_chart(
                            "rankedScore", score.previous_best.score, score.score
                        ),
                        Beatmap.add_chart(
                            "totalScore", score.previous_best.score, score.score
                        ),
                        Beatmap.add_chart(
                            "pp", math.ceil(score.previous_best.pp), math.ceil(score.pp)
                        ),
                    )
                ),
                f"onlineScoreId:{score.id}",
            )
        )
    )

    response.append(
        "|".join(
            (
                "chartId:overall",
                f"chartUrl:{score.player.url}",
                "chartName:Overall Ranking",
                *(
                    (
                        Beatmap.add_chart("rank", after=stats.rank),
                        Beatmap.add_chart("accuracy", after=stats.accuracy),
                        Beatmap.add_chart("maxCombo", after=0),
                        Beatmap.add_chart("rankedScore", prev=stats.ranked_score),
                        Beatmap.add_chart("totalScore", after=stats.total_score),
                        Beatmap.add_chart("pp", after=stats.pp),
                    )
                    if not prev_stats
                    else (
                        Beatmap.add_chart("rank", prev_stats.rank, stats.rank),
                        Beatmap.add_chart(
                            "accuracy", prev_stats.accuracy, stats.accuracy
                        ),
                        Beatmap.add_chart("maxCombo", 0, 0),
                        Beatmap.add_chart(
                            "rankedScore",
                            prev_stats.ranked_score,
                            stats.ranked_score,
                        ),
                        Beatmap.add_chart(
                            "totalScore",
                            prev_stats.total_score,
                            stats.total_score,
                        ),
                        Beatmap.add_chart("pp", prev_stats.pp, stats.pp),
                    )
                ),
                f"achievements-new:{achievements}",
            )
        )
    )

    return Response(content="\n".join(response).encode())


@osu.route("/web/osu-getreplay.php")
@check_auth("u", "h")
async def get_replay(request: Request, player: Player) -> Response:
    await player.update_latest_activity()

    score_id = request.query_params["c"]

    if not os.path.exists(path := f".data/replays/{score_id}.osr"):
        services.logger.error(
            f"replay for {score_id} cannot be loaded, because it doesn't exist."
        )
        return Response(content=b"")

    score_info = await services.database.fetch_one(
        "SELECT user_id, mode, gamemode FROM scores WHERE id = :score_id",
        {"score_id": score_id},
    )

    if not score_info:
        return Response(content=b"")

    if score_info["user_id"] != player.id:
        await services.database.execute(
            "INSERT INTO replay_views (user_id, score_id) "
            "VALUES (:user_id, :score_id)",
            {"user_id": player.id, "score_id": score_id},
        )

        gamemode = Gamemode(score_info["gamemode"])
        mode = Mode(score_info["mode"])

        # since the Mode.to_db() function returns the
        # field with a new name we have to remove it.
        to_db = mode.to_db("replays_watched_by_others").split(" as")[0]

        await services.database.execute(
            f"UPDATE {gamemode.to_db} SET {to_db} = {to_db} + 1 WHERE id = :user_id",
            {"user_id": score_info["user_id"]},
        )

    return FileResponse(path=path)


@osu.route("/web/osu-getfriends.php")
@check_auth("u", "h")
async def get_friends(request: Request, player: Player) -> Response:
    await player.get_friends()

    return Response(content="\n".join(map(str, player.friends)).encode())


@osu.route("/web/osu-markasread.php")
@check_auth("u", "h")
async def markasread(request: Request, player: Player) -> Response:
    # not doing this
    return Response(content=b"")


@osu.route("/web/lastfm.php")
@check_auth("us", "ha")
async def lastfm(request: Request, player: Player) -> Response:
    # something odd in client detected
    if not (_flag := request.query_params["b"]):
        return Response(content=b"")

    if _flag[0] != "a":
        return Response(content=b"-3")

    flag = int(_flag[1:])

    services.logger.debug(flag)

    # if nothing odd happens... then keep checking
    return Response(content=b"")


@osu.route("/web/osu-getseasonal.php")
async def get_seasonal(request: Request) -> Response:
    # hmmm... it seems like there's nothing special yet
    # TODO: make a config file for this?
    services.logger.debug("getting seasonal background")
    return general.ORJSONResponse(
        [
            "https://steamuserimages-a.akamaihd.net/ugc/1756934458426121120/870EB09212BCB5CC5FEFA9619BE83242DAECE498/?imw=637&imh=358&ima=fit&impolicy=Letterbox&imcolor=%23000000&letterbox=true"
        ]
    )


@osu.route("/web/osu-error.php", methods=["POST"])
async def get_osu_error(request: Request) -> Response:
    # not really our problem though :trolley:
    # let's just send this empty thing
    services.logger.error("osu sent an error")
    return Response(content=b"")


@osu.route("/web/osu-comment.php", methods=["POST"])
@check_auth("u", "p", method="POST")
async def get_beatmap_comments(request: Request, player: Player) -> Response:
    return Response(content=b"")


@osu.route("/web/osu-screenshot.php", methods=["POST"])
@check_auth("u", "p", method="POST")
async def post_screenshot(request: Request, player: Player) -> Response:
    await player.update_latest_activity()

    id = general.random_string(8)
    form = await request.form()

    async with aiofiles.open(f".data/ss/{id}.png", "wb+") as screenshot:
        await screenshot.write(await form["ss"].read())  # type: ignore

    return Response(content=f"{id}.png".encode())


@osu.route("/ss/{ssid:str}.png")
async def get_screenshot(req: Request) -> FileResponse | Response:
    if os.path.exists(path := f".data/ss/{req.path_params['ssid']}.png"):
        return FileResponse(path=path)

    return Response(content=b"screenshot doesn't exist.")


@osu.route("/web/osu-search.php")
@check_auth("u", "h")
async def osu_direct(request: Request, player: Player) -> Response:
    await player.update_latest_activity()

    args = request.query_params

    match args["r"]:
        case "2":
            ranking = "pending"
        case "3":
            ranking = "qualified"
        case "4":
            ranking = "all"
        case "5":
            ranking = "graveyard"
        case "8":
            ranking = "loved"
        case _:
            ranking = "ranked"

    if (query := args["q"]) in ("Newest", "Top+Rated", "Most+Played"):
        query = ""

    if (mode := args["m"]) == "-1":
        mode = "all"

    url = f"https://api.nerinyan.moe/search"
    url += f"?p={query}"
    url += f"&m={query}"
    url += f"&ps=100"
    url += f"&s={ranking}"
    url += "&sort=updated_desc" if ranking in ("all", "pending", "graveyard") else ""
    url += f"&p={args["p"]}"

    map_count = 0
    direct_list = ""

    response = await services.http_client_session.get(url)
    data = await response.json()

    if len(data) == 100:
        map_count = 1

    for map in data:
        map_count += 1

        set_id = map["id"]
        artist = map["artist"]
        title = map["title"]
        creator = map["creator"]
        ranked = map["ranked"]

        last_updated = map["last_updated"]

        thread_id = map["legacy_thread_url"][43:]  # remove osu link and get only id
        has_video = "1" if map["video"] else ""
        has_storyboard = "1" if map["storyboard"] else ""

        direct_list += f"{set_id}.osz|{artist}|{title}|{creator}|{ranked}|"
        direct_list += (
            f"10|{last_updated}|{set_id}|{thread_id}|{has_video}|{has_storyboard}|0||"
        )

        for i, child_map in enumerate(map["beatmaps"]):
            difficulty_name = child_map["version"]
            star_rating = child_map["difficulty_rating"]
            mode = child_map["mode_int"]

            direct_list += f"{difficulty_name.replace(',', '').replace('|', 'ǀ')} ★{star_rating}@{mode}"

            if i < len(map["beatmaps"]) - 1:
                direct_list += ","
            else:
                direct_list += "\n"

    return Response(content=str(map_count).encode() + b"\n" + direct_list.encode())


@osu.route("/web/osu-search-set.php")
@check_auth("u", "h")
async def osu_search_set(request: Request, player: Player) -> Response:
    await player.update_latest_activity()

    match request.query_params:
        # There's also "p" (post) and "t" (topic) too, but who uses that in private server?
        case {"s": sid}:  # Beatmap Set
            # todo
            map = None
        case {"b": bid}:  # Beatmap ID
            map = await services.beatmaps.get_by_map_id(bid)  # type: ignore
        case {"c": hash}:  # Checksum
            map = await services.beatmaps.get(hash)  # type: ignore
        case _:
            map = None

    if not map:  # if beatmap doesn't exists in db then fetch!
        services.logger.critical(
            "failed to get map, as it doesn't exist in the database."
        )
        return Response(content=b"xoxo gossip girl")

    return Response(
        content=f"{map.set_id}.osz|{map.artist}|{map.title}|"
        f"{map.creator}|{map.approved.to_osu}|{map.rating}|"
        f"{map.latest_update}|{map.set_id}|"
        "0|0|0|0|0".encode()
    )


@osu.route("/d/{map_id:int}")
@osu.route("/d/{map_id:int}n")  # no video
async def download_osz(request: Request) -> Response:
    # TODO: check for availablity, if not use another mirror.

    return RedirectResponse(
        url=f"https://api.nerinyan.moe/d/{request.path_params['map_id']}{'?noVideo=true' if request.url.path[-1] == 'n' else ''}",
        status_code=301,
    )


@osu.route("/web/bancho_connect.php")
@check_auth("u", "h")
async def bancho_connect(request: Request, player: Player) -> Response:
    # TODO: proper verification
    return Response(content=f"https://c.{services.domain}".encode())

from enum import IntEnum, unique
import os
import time
import math
import copy
import bcrypt
import aiohttp
import hashlib
import asyncio
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
from constants.beatmap import Approved
from starlette.requests import Request
from constants.player import Privileges
from objects.score import Score, SubmitStatus
from starlette.responses import FileResponse, Response, RedirectResponse


def check_auth(
    u: str,
    pw: str,
    # cho_auth: bool = False,
    custom_resp: bytes | None = None,
    method="GET",
):
    def decorator(cb: Callable) -> Callable:
        @wraps(cb)
        async def wrapper(req, *args, **kwargs):
            if method == "GET":
                if u not in req.query_params or pw not in req.query_params:
                    return Response(content=custom_resp or b"not allowed")

                player = unquote(req.query_params[u])
                password = req.query_params[pw]
            else:
                form = await req.form()

                if u not in form or pw not in form:
                    return Response(content=custom_resp or b"not allowed")

                player = unquote(form[u])
                password = form[pw]

            # if not cho_auth:
            if not (p := services.players.get(player)):
                return Response(content=custom_resp or b"not allowed")

            if p.passhash in services.bcrypt_cache:
                if password.encode("utf-8") != services.bcrypt_cache[p.passhash]:
                    return Response(content=custom_resp or b"not allowed")

            return await cb(req, p, *args, **kwargs)

        return wrapper

    return decorator


osu = Router()


@osu.route("/users", methods=["POST"])
async def registration(req: Request) -> Response:
    form = await req.form()
    username = form["user[username]"]
    email = form["user[user_email]"]
    pwd = form["user[password]"]

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
        pw_md5 = hashlib.md5(pwd.encode()).hexdigest().encode()
        pw_bcrypt = bcrypt.hashpw(pw_md5, bcrypt.gensalt())

        id = await services.database.execute(
            "INSERT INTO users (username, safe_username, passhash, "
            "email, privileges, latest_activity_time, registered_time) "
            "VALUES (:username, :safe_username, :passhash, :email, :privileges, UNIX_TIMESTAMP(), UNIX_TIMESTAMP())",
            {
                "username": username,
                "safe_username": username.lower().replace(" ", "_"),
                "passhash": pw_bcrypt,
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


async def save_beatmap_file(id: int) -> None | Response:
    if not os.path.exists(f".data/beatmaps/{id}.osu"):
        async with aiohttp.ClientSession() as sess:
            async with sess.get(
                f"https://osu.ppy.sh/web/osu-getosufile.php?q={id}",
                headers={"user-agent": "osu!"},
            ) as resp:
                if not await resp.text():
                    services.logger.critical(
                        f"Couldn't fetch the .osu file of {id}. Maybe because api rate limit?"
                    )
                    return Response(content=b"")

                async with aiofiles.open(f".data/beatmaps/{id}.osu", "w+") as osu:
                    await osu.write(await resp.text())


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
async def get_scores(req: Request, p: Player) -> Response:
    hash = req.query_params["c"]

    if not (b := await services.beatmaps.get(hash)):
        return Response(content=b"-1|true")

    # don't cache maps that doesn't have leaderboard
    if not b.approved.has_leaderboard:
        services.beatmaps.remove(b.map_md5)

        return Response(content=f"{b.approved.to_osu}|false".encode())

    mods = int(req.query_params["mods"])

    # switch user to  the respective gamemode based on leaderboard mods.
    prev_gamemode = p.gamemode
    p.gamemode = Gamemode.RELAX if mods & Mods.RELAX else Gamemode.VANILLA

    # enqueue respective stats if gamemode has changed
    if prev_gamemode != p.gamemode:
        await p.update_stats_cache()
        services.players.enqueue(writer.update_stats(p))

    ret = [b.web_format]

    mode = int(req.query_params["m"])

    query = (
        "SELECT s.id as id_, COALESCE(CONCAT('[', c.tag, '] ', u.username), u.username) as username, "
        "s.max_combo, s.count_50, s.count_100, s.count_300, s.count_miss, s.count_katu, "
        f"CAST(s.{p.gamemode.score_order} as INT) as score, s.submitted, s.count_geki, s.perfect, "
        "s.mods, s.user_id, u.country FROM scores s INNER JOIN users u ON u.id = s.user_id "
        "LEFT JOIN clans c ON c.id = u.clan_id WHERE s.map_md5 = :map_md5 AND s.mode = :mode "
        "AND s.status = 3 AND u.privileges & 4 AND s.gamemode = :gamemode "
    )
    params = {"map_md5": b.map_md5, "mode": mode, "gamemode": p.gamemode.value}

    board_type = LeaderboardType(int(req.query_params["v"]))

    match board_type:
        case LeaderboardType.MODS:
            query += "AND mods = :mods "
            params["mods"] = mods
        case LeaderboardType.COUNTRY:
            query += "AND u.country = :country "
            params["country"] = p.country
        case LeaderboardType.FRIENDS:
            query += "AND s.user_id IN :friends "
            params["friends"] = p.friends

    query += f"ORDER BY score DESC, s.submitted ASC LIMIT 50"
    personal_best = await services.database.fetch_one(
        f"SELECT s.id as id_, CAST(s.{p.gamemode.score_order} as INT) as score, "
        "s.max_combo, s.count_50, s.count_100, s.count_300, s.count_miss, s.count_katu, "
        "s.count_geki, s.perfect, s.mods, s.submitted FROM scores s WHERE s.status = 3 "
        "AND s.map_md5 = :map_md5 AND s.gamemode = :gamemode AND s.mode = :mode "
        "AND s.user_id = :user_id LIMIT 1",
        {
            "map_md5": b.map_md5,
            "gamemode": p.gamemode.value,
            "mode": mode,
            "user_id": p.id,
        },
    )

    if not personal_best:
        ret.append("")
    else:
        pb_position = await services.database.fetch_val(
            "SELECT COUNT(*) FROM scores s "
            "INNER JOIN beatmaps b ON b.map_md5 = s.map_md5 "
            "INNER JOIN users u ON u.id = s.user_id "
            f"WHERE s.{p.gamemode.score_order} > :pb_score "
            "AND s.gamemode = :gamemode AND s.map_md5 = :map_md5 "
            "AND u.privileges & 4 AND s.status = 3 "
            "AND s.mode = :mode",
            {
                "pb_score": personal_best["score"],
                "gamemode": p.gamemode.value,
                "map_md5": b.map_md5,
                "mode": mode,
            },
        )

        if pb_position:
            ret.append(
                SCORES_FORMAT.format(
                    **dict(personal_best),
                    user_id=p.id,
                    username=p.username_with_tag,
                    position=pb_position + 1,
                )
            )  # type: ignore

    top_scores = await services.database.fetch_all(query, params)

    ret.extend(
        [
            SCORES_FORMAT.format(**dict(score), position=idx + 1)
            for idx, score in enumerate(top_scores)
        ]
    )

    asyncio.create_task(save_beatmap_file(b.map_id))

    return Response(content="\n".join(ret).encode())


@osu.route("/web/osu-submit-modular-selector.php", methods=["POST"])
async def score_submission(req: Request) -> Response:
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

    # The dict is empty for some reason... odd..
    form = await req.form()

    if not form:
        return Response(content=b"error: missinginfo")

    # TODO: make this work properly
    # if (ver := form["osuver"])[:4] != "2023":
    #     return Response(content=b"error: oldver")

    submission_key = f"osu!-scoreburgr---------{form["osuver"]}"

    s = await Score.set_data_from_submission(
        form.getlist("score")[0],
        form["iv"],
        submission_key,
        int(form["x"]),
    )

    if not s or not s.player or not s.map or s.player.is_restricted:
        return Response(content=b"error: beatmap")

    if not s.player.privileges & Privileges.VERIFIED:
        return Response(content=b"error: verify")

    if s.mods & Mods.DISABLED:
        return Response(content=b"error: disabled")

    passed = s.status >= SubmitStatus.PASSED

    # get current first place holder, if any
    cur_fp = await services.database.fetch_val(
        "SELECT s.user_id FROM scores s INNER JOIN users u ON u.id = s.user_id "
        "WHERE s.map_md5 = :map_md5 AND s.mode = :mode AND s.gamemode = :gamemode "
        " AND u.privileges & 4 ORDER BY s.pp DESC LIMIT 1",
        {"map_md5": s.map.map_md5, "mode": s.mode, "gamemode": s.gamemode},
    )

    s.playtime = int(form["st" if passed else "ft"]) // 1000  # milliseconds
    s.id = await s.save_to_db()
    s.map.plays += 1

    # check if the beatmap playcount for player exists first
    # if it does, we just wanna update.
    if beatmap_playcount := await services.database.fetch_val(
        "SELECT id FROM beatmap_playcount WHERE map_md5 = :map_md5 "
        "AND user_id = :user_id AND mode = :mode AND gamemode = :gamemode",
        {
            "map_md5": s.map.map_md5,
            "user_id": s.player.id,
            "mode": s.mode,
            "gamemode": s.gamemode,
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
                "map_md5": s.map.map_md5,
                "user_id": s.player.id,
                "mode": s.mode,
                "gamemode": s.gamemode,
            },
        )

    if not passed:
        return Response(content=b"error: no")

    stats = s.player

    # check if the user is playing the map for the first time
    prev_stats = None

    if stats.total_score > 0:
        prev_stats = copy.copy(stats)

    # save replay
    with open(f".data/replays/{s.id}.osr", "wb+") as file:
        file.write(await form["score"].read())

    # update map passes
    s.map.passes += 1

    # restrict the player if they
    # somehow managed to submit a
    # score without a replay.
    if not form.getlist("score"):
        await s.player.restrict()
        return Response(content=b"error: invalid")

    await services.database.execute(
        "UPDATE beatmaps SET plays = :plays, passes = :passes WHERE map_md5 = :map_md5",
        {"plays": s.map.plays, "passes": s.map.passes, "map_md5": s.map.map_md5},
    )

    # calculate new stats
    if not s.map.approved.has_leaderboard:
        return Response(content=b"error: no")

    stats.playcount += 1
    stats.total_score += s.score
    stats.total_hits += s.total_hits

    if s.status == SubmitStatus.BEST:
        sus = s.score

        if s.pb:
            sus -= s.pb.score

        stats.ranked_score += sus

        scores = await services.database.fetch_all(
            "SELECT pp, accuracy, awards_pp FROM scores "
            "WHERE user_id = :user_id AND mode = :mode "
            "AND status = 3 AND gamemode = :gamemode "
            "AND awards_pp = 1 ORDER BY pp DESC LIMIT 100",
            {"user_id": stats.id, "mode": s.mode.value, "gamemode": s.gamemode.value},
        )

        stats.accuracy = np.sum(
            [score["accuracy"] * 0.95**place for place, score in enumerate(scores)]
        )  # type: ignore
        stats.accuracy *= 100 / (20 * (1 - 0.95 ** len(scores)))
        stats.accuracy /= 100

        if s.map.approved.awards_pp:
            all_awarded_pp_scores = [score for score in scores if score[2] == 1]
            weighted = np.sum(
                [
                    score["pp"] * 0.95 ** (place)
                    for place, score in enumerate(all_awarded_pp_scores)
                ]
            )  # type: ignore
            weighted += 416.6667 * (1 - 0.9994 ** len(all_awarded_pp_scores))
            stats.pp = math.ceil(weighted)

            stats.rank = await stats.update_rank(s.gamemode, s.mode)

        await stats.update_stats(s)
        services.players.enqueue(writer.update_stats(stats))

        # if the player got first place
        # on the map announce it
        if s.position == 1 and not stats.is_restricted:
            chan = services.channels.get("#announce")
            assert chan is not None

            gamemode = "[Relax]" if s.gamemode == Gamemode.RELAX else ""

            chan.send(
                f"{s.player.embed} achieved #{s.position} on {
                    s.map.embed} ({s.mode.to_string()}) {gamemode}",
                sender=services.bot,
            )

            # announce that the previous first place holder
            # lost their rank 1 on this map in their recent activities
            if cur_fp and cur_fp["user_id"] != s.player.id:
                await services.database.execute(
                    "INSERT INTO recent_activities (user_id, activity, map_md5, mode, gamemode) "
                    "VALUES (:user_id, :activity, :map_md5, :mode, :gamemode)",
                    {
                        "user_id": cur_fp,
                        "activity": "lost rank #1 on",
                        "map_md5": s.map.map_md5,
                        "mode": s.mode,
                        "gamemode": s.gamemode,
                    },
                )

            # put it into the new first place holders recent activities.
            await services.database.execute(
                "INSERT INTO recent_activities (user_id, activity, map_md5, mode, gamemode) "
                "VALUES (:user_id, :activity, :map_md5, :mode, :gamemode)",
                {
                    "user_id": cur_fp,
                    "activity": "achieved rank #1 on",
                    "map_md5": s.map.map_md5,
                    "mode": s.mode,
                    "gamemode": s.gamemode,
                },
            )

    # TODO: map difficulty changing mods

    _achievements = []
    for ach in services.achievements:
        user_achievement = UserAchievement(
            **ach.__dict__, gamemode=s.gamemode, mode=s.mode
        )

        if user_achievement in stats.achievements:
            continue

        # if the achievement condition matches
        # with the score, it should be unlocked.
        try:
            if eval(ach.condition):
                services.logger.info(
                    f"{stats.username} unlocked {ach.name} that has condition: {ach.condition}"
                )
                await services.database.execute(
                    "INSERT INTO users_achievements (user_id, achievement_id, mode, gamemode) "
                    "VALUES (:user_id, :achievement_id, :mode, :gamemode)",
                    {
                        "user_id": stats.id,
                        "achievement_id": ach.id,
                        "mode": s.mode.value,
                        "gamemode": s.gamemode.value,
                    },
                )

                stats.achievements.append(user_achievement)
                _achievements.append(ach)
        except:
            # usual "failed" conditions, if because the Player.last_score is none
            continue

    achievements = "/".join(str(ach) for ach in _achievements)
    gamemode = "[Relax]" if s.gamemode == Gamemode.RELAX else ""

    services.logger.info(
        f"{stats.username} submitted a score on {
            s.map.full_title} ({s.mode.to_string()}: {s.pp}pp) {gamemode}"
    )

    # cache the score as the latest score on current player session.
    s.player.last_score = s

    # only do charts if the score isn't relax
    # but do charts if the user is playing on rina
    ret: list = []
    if s.gamemode != Gamemode.VANILLA and not stats.using_rina:
        return Response(content=b"error: no")

    ret.append(
        "|".join(
            (
                f"beatmapId:{s.map.map_id}",
                f"beatmapSetId:{s.map.set_id}",
                f"beatmapPlaycount:{s.map.plays}",
                f"beatmapPasscount:{s.map.passes}",
                f"approvedDate:{s.map.approved_date}",
            )
        )
    )

    ret.append(
        "|".join(
            (
                "chartId:beatmap",
                f"chartUrl:{s.map.url}",
                "chartName:Beatmap Ranking",
                *(
                    (
                        Beatmap.add_chart("rank", after=s.position),
                        Beatmap.add_chart("accuracy", after=s.accuracy),
                        Beatmap.add_chart("maxCombo", after=s.max_combo),
                        Beatmap.add_chart("rankedScore", after=s.score),
                        Beatmap.add_chart("totalScore", after=s.score),
                        Beatmap.add_chart("pp", after=math.ceil(s.pp)),
                    )
                    if not s.pb
                    else (
                        Beatmap.add_chart("rank", s.pb.position, s.position),
                        Beatmap.add_chart("accuracy", s.pb.accuracy, s.accuracy),
                        Beatmap.add_chart("maxCombo", s.pb.max_combo, s.max_combo),
                        Beatmap.add_chart("rankedScore", s.pb.score, s.score),
                        Beatmap.add_chart("totalScore", s.pb.score, s.score),
                        Beatmap.add_chart("pp", math.ceil(s.pb.pp), math.ceil(s.pp)),
                    )
                ),
                f"onlineScoreId:{s.id}",
            )
        )
    )

    ret.append(
        "|".join(
            (
                "chartId:overall",
                f"chartUrl:{s.player.url}",
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

    return Response(content="\n".join(ret).encode())


@osu.route("/web/osu-getreplay.php")
@check_auth("u", "h")
async def get_replay(req: Request, p: Player) -> Response:
    score_id = req.query_params["c"]

    if not os.path.isfile(path := f".data/replays/{score_id}.osr"):
        services.logger.info(
            f"Replay ID {score_id} cannot be loaded! (File not found?)"
        )
        return Response(content=b"")

    score_info = await services.database.fetch_one(
        "SELECT user_id, mode, gamemode FROM scores WHERE id = :score_id",
        {"score_id": score_id},
    )

    if not score_info:
        return Response(content=b"")

    if score_info["user_id"] != p.id:
        await services.database.execute(
            "INSERT INTO replay_views (user_id, score_id) "
            "VALUES (:user_id, :score_id)",
            {"user_id": p.id, "score_id": score_id},
        )

        gamemode = Gamemode(score_info["gamemode"])
        play_mode = Mode(score_info["mode"])

        # since the Mode.to_db() function returns the
        # field with a new name we have to remove it.
        to_db = play_mode.to_db("replays_watched_by_others").split(" as")[0]

        await services.database.execute(
            f"UPDATE {gamemode.table} SET {to_db} = {to_db} + 1 WHERE id = :user_id",
            {"user_id": score_info["user_id"]},
        )

    return FileResponse(path=path)


@osu.route("/web/osu-getfriends.php")
@check_auth("u", "h")
async def get_friends(req: Request, p: Player) -> Response:
    await p.get_friends()

    return Response(content="\n".join(map(str, p.friends)).encode())


@osu.route("/web/osu-markasread.php")
@check_auth("u", "h")
async def markasread(req: Request, p: Player) -> Response:
    if not (chan := services.channels.get(req.query_params["channel"])):
        return Response(content=b"")

    # TODO: maybe make a mail system???
    return Response(content=b"")


@osu.route("/web/lastfm.php")
@check_auth("us", "ha")
async def lastfm(req: Request, p: Player) -> Response:
    # something odd in client detected
    if not (_flag := req.query_params["b"]):
        return Response(content=b"")

    if _flag[0] != "a":
        return Response(content=b"-3")

    flag = int(_flag[1:])

    services.logger.debug(flag)

    # if nothing odd happens... then keep checking
    return Response(content=b"")


@osu.route("/web/osu-getseasonal.php")
async def get_seasonal(req: Request) -> Response:
    # hmmm... it seems like there's nothing special yet
    # TODO: make a config file for this?
    services.logger.debug("getting seasonal background")
    return general.ORJSONResponse(
        [
            "https://steamuserimages-a.akamaihd.net/ugc/1756934458426121120/870EB09212BCB5CC5FEFA9619BE83242DAECE498/?imw=637&imh=358&ima=fit&impolicy=Letterbox&imcolor=%23000000&letterbox=true"
        ]
    )


@osu.route("/web/osu-error.php", methods=["POST"])
async def get_osu_error(req: Request) -> Response:
    # not really our problem though :trolley:
    # let's just send this empty thing
    services.logger.error("osu sent an error")
    return Response(content=b"")


@osu.route("/web/osu-comment.php", methods=["POST"])
@check_auth("u", "p", method="POST")
async def get_beatmap_comments(req: Request, p: Player) -> Response:
    return Response(content=b"")


@osu.route("/web/osu-screenshot.php", methods=["POST"])
@check_auth("u", "p", method="POST")
async def post_screenshot(req: Request, p: Player) -> Response:
    id = general.random_string(8)
    form = await req.form()

    async with aiofiles.open(f".data/ss/{id}.png", "wb+") as ss:
        await ss.write(await form["ss"].read())

    return Response(content=f"{id}.png".encode())


@osu.route("/ss/{ssid:str}.png")
async def get_screenshot(req: Request) -> FileResponse | Response:
    if os.path.isfile(path := f".data/ss/{req.path_params['ssid']}.png"):
        return FileResponse(path=path)

    return Response(content=b"no screenshot with that id.")


@osu.route("/web/osu-search.php")
@check_auth("u", "h")
async def osu_direct(req: Request, p: Player) -> Response:
    args = req.query_params

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

    url = f"https://api.nerinyan.moe/search?q={query}&m={mode}&ps=100&s={ranking}{
        '&sort=updated_desc' if ranking in ('all', 'pending', 'graveyard') else ''}&p={args['p']}"
    bmCount = 0
    directList = ""

    async with aiohttp.ClientSession() as sess:
        async with sess.get(url) as resp:
            data = await resp.json()

            if len(data) == 100:
                bmCount = 1

            for beatmapset in data:
                bmCount += 1

                sid = beatmapset["id"]
                artist = beatmapset["artist"]
                title = beatmapset["title"]
                creator = beatmapset["creator"]
                ranked = beatmapset["ranked"]

                lastUpd = beatmapset["last_updated"]

                threadId = beatmapset["legacy_thread_url"][
                    43:
                ]  # remove osu link and get only id
                hasVideo = "1" if beatmapset["video"] else ""
                hasStoryboard = "1" if beatmapset["storyboard"] else ""

                directList += f"{sid}.osz|{artist}|{title}|{creator}|{ranked}|"
                directList += f"10|{lastUpd}|{sid}|{threadId}|{
                        hasVideo}|{hasStoryboard}|0||"

                for i, beatmaps in enumerate(beatmapset["beatmaps"]):
                    diffName = beatmaps["version"]
                    starsRating = beatmaps["difficulty_rating"]
                    mode = beatmaps["mode_int"]

                    directList += f"{diffName.replace(',', '').replace('|', 'ǀ')} ★{
                        starsRating}@{mode}"

                    if i < len(beatmapset["beatmaps"]) - 1:
                        directList += ","
                    else:
                        directList += "\n"

    return Response(content=str(bmCount).encode() + b"\n" + directList.encode())


@osu.route("/web/osu-search-set.php")
@check_auth("u", "h")
async def osu_search_set(req: Request, p: Player) -> Response:
    match req.query_params:
        # There's also "p" (post) and "t" (topic) too, but who uses that in private server?
        case {"s": sid}:  # Beatmap Set
            bmap = await services.beatmaps.get_by_set_id(sid)
        case {"b": bid}:  # Beatmap ID
            bmap = await services.beatmaps.get_by_map_id(bid)  # type: ignore
        case {"c": hash}:  # Checksum
            bmap = await services.beatmaps.get(hash)  # type: ignore
        case _:
            bmap = None

    if not bmap:  # if beatmap doesn't exists in db then fetch!
        services.logger.critical(
            "/web/osu-search-set.php: Failed to get map (probably doesn't exist)"
        )
        return Response(content=b"xoxo gossip girl")

    return Response(
        content=f"{bmap.set_id}.osz|{bmap.artist}|{bmap.title}|"
        f"{bmap.creator}|{bmap.approved.to_osu}|{bmap.rating}|"
        f"{bmap.latest_update}|{bmap.set_id}|"
        "0|0|0|0|0".encode()
    )


@osu.route("/d/{map_id:int}")
@osu.route("/d/{map_id:int}n")  # no video
async def download_osz(req: Request) -> Response:
    # TODO: check for availablity, if not use another mirror.

    return RedirectResponse(
        url=f"https://api.nerinyan.moe/d/{req.path_params['map_id']}{
            '?noVideo=true' if req.url.path[-1] == 'n' else ''}",
        status_code=301,
    )


@osu.route("/web/bancho_connect.php")
@check_auth("u", "h")
async def bancho_connect(req: Request, p: Player) -> Response:
    # TODO: proper verification
    return Response(content=f"https://c.{services.domain}".encode())

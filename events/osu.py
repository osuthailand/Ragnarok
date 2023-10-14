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

from utils import log
from utils import general
from functools import wraps
from objects import services
from collections import defaultdict
from typing import Callable

from objects.player import Player
from constants.mods import Mods
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

            # if not (
            #     user_info := await services.sql.fetch(
            #         "SELECT username, id, privileges, "
            #         "passhash, lon, lat, country, cc FROM users "
            #         "WHERE safe_username = %s",
            #         [player.lower().replace(" ", "_")],
            #     )
            # ):
            #     return Response(content=custom_resp or b"not allowed")

            # phash = user_info["passhash"].encode("utf-8")
            # pmd5 = password.encode("utf-8")

            # if phash in services.bcrypt_cache:
            #     if pmd5 != services.bcrypt_cache[phash]:
            #         log.warn(
            #             f"USER {user_info['username']} ({user_info['id']}) | Login fail. (WRONG PASSWORD)"
            #         )

            #         return Response(content=custom_resp or b"not allowed")
            # else:
            #     if not bcrypt.checkpw(pmd5, phash):
            #         log.warn(
            #             f"USER {user_info['username']} ({user_info['id']}) | Login fail. (WRONG PASSWORD)"
            #         )

            #         return Response(content=custom_resp or b"not allowed")

            #     services.bcrypt_cache[phash] = pmd5

            # return await cb(req, *args, **kwargs)

        return wrapper

    return decorator


osu = Router()


@osu.route("/users", methods=["POST"])
async def registration(req: Request) -> Response:
    form = await req.form()
    uname = form["user[username]"]
    email = form["user[user_email]"]
    pwd = form["user[password]"]

    error_response = defaultdict(list)

    if await services.sql.fetch("SELECT 1 FROM users WHERE username = %s", [uname]):
        error_response["username"].append(
            "A user with that name already exists in our database."
        )

    if await services.sql.fetch("SELECT 1 FROM users WHERE email = %s", [email]):
        error_response["user_email"].append(
            "A user with that email already exists in our database."
        )

    if error_response:
        return general.ORJSONResponse(
            status_code=400, content={"form_error": {"user": error_response}}
        )

    # TODO: website registration config
    # if services.web_register:
    # osu! will attempt to go to https://url?username={username}&email={email}
    # return ORJSONResponse(status_code=403, content={"error":"please register from Rina website","url":"https:\/\/rina.place\/register"}})

    if form["check"] == "0":
        pw_md5 = hashlib.md5(pwd.encode()).hexdigest().encode()
        pw_bcrypt = bcrypt.hashpw(pw_md5, bcrypt.gensalt())

        id = await services.sql.execute(
            "INSERT INTO users (id, username, safe_username, passhash, "
            "email, privileges, latest_activity_time, registered_time) "
            "VALUES (NULL, %s, %s, %s, %s, %s, UNIX_TIMESTAMP(), UNIX_TIMESTAMP())",
            [
                uname,
                uname.lower().replace(" ", "_"),
                pw_bcrypt,
                email,
                Privileges.PENDING.value,
            ],
        )

        await services.sql.execute("INSERT INTO stats (id) VALUES (%s)", [id])
        await services.sql.execute("INSERT INTO stats_rx (id) VALUES (%s)", [id])

    return Response(content=b"ok")


async def save_beatmap_file(id: int) -> None | Response:
    if not os.path.exists(f".data/beatmaps/{id}.osu"):
        async with aiohttp.ClientSession() as sess:
            async with sess.get(
                f"https://osu.ppy.sh/web/osu-getosufile.php?q={id}",
                headers={"user-agent": "osu!"},
            ) as resp:
                if not await resp.text():
                    log.fail(
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
    if not b.approved & Approved.HAS_LEADERBOARD:
        services.beatmaps.remove(b.hash_md5)

        return Response(content=f"{b.approved.to_osu}|false".encode())

    mods = int(req.query_params["mods"])

    # switch user to relax, when they have the relax mod enabled
    if not mods & Mods.RELAX and p.relax:
        p.relax = 0
    elif mods & Mods.RELAX and not p.relax:
        p.relax = 1

    ret = [b.web_format]

    order = ("score", "pp")[p.relax]

    mode = int(req.query_params["m"])

    query = (
        f"SELECT s.id as id_, u.username, CAST(s.{order} as INT) as score, s.submitted, s.max_combo, "
        "s.count_50, s.count_100, s.count_300, s.count_miss, s.count_katu, "
        "s.count_geki, s.perfect, s.mods, s.user_id, u.country FROM scores s "
        f"INNER JOIN users u ON u.id = s.user_id WHERE s.hash_md5 = '{hash}' "
        f"AND s.status = 3 AND u.privileges & 4 AND s.relax = {int(p.relax)} "
        f"AND mode = {mode} "
    )

    board_type = LeaderboardType(int(req.query_params["v"]))

    match board_type:
        case LeaderboardType.MODS:
            query += f"AND mods = {mods} "
        case LeaderboardType.COUNTRY:
            query += f"AND u.country = {p.country} "
        case LeaderboardType.FRIENDS:
            # this is absolutely so fucking ugly
            # but i dont know what else works rn
            friends = f"({', '.join(str(x) for x in (p.friends | {p.id}))})"
            query += f"AND s.user_id IN {friends} "

    query += f"ORDER BY score DESC, s.submitted ASC LIMIT 50"

    personal_best = await services.sql.fetch(
        f"SELECT s.id as id_, CAST(s.{order} as INT) as score, s.max_combo, "
        "s.count_50, s.count_100, s.count_300, s.count_miss, s.count_katu, "
        "s.count_geki, s.perfect, s.mods, s.submitted FROM scores s WHERE s.status = 3 "
        "AND s.hash_md5 = %s AND s.relax = %s AND s.mode = %s AND s.user_id = %s LIMIT 1",
        (b.hash_md5, p.relax, mode, p.id)
    )

    if not personal_best:
        ret.append("")
    else:
        pb_position = await services.sql.fetch(
            "SELECT COUNT(*) FROM scores s "
            "INNER JOIN beatmaps b ON b.hash = s.hash_md5 "
            "INNER JOIN users u ON u.id = s.user_id "
            f"WHERE s.{order} > {personal_best['score']} "
            "AND s.relax = %s AND b.hash = %s  "
            "AND u.privileges & 4 AND s.status = 3 "
            "AND s.mode = %s",
            (p.relax, b.hash_md5, mode),
            _dict=False
        )

        if pb_position:
            ret.append(SCORES_FORMAT.format(**personal_best,
                                            user_id=p.id, username=p.username, position=pb_position[0] + 1))  # type: ignore

    top_scores = await services.sql.fetchall(query, _dict=True)

    ret.extend([
        SCORES_FORMAT.format(
            **score,
            position=idx + 1
        )
        for idx, score in enumerate(top_scores)
    ])

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

    if (ver := form["osuver"])[:4] != "2023":
        return Response(content=b"error: oldver")

    submission_key = f"osu!-scoreburgr---------{ver}"

    s = await Score.set_data_from_submission(
        form.getlist("score")[0],
        form["iv"],
        submission_key,
        int(form["x"]),
    )

    if (
        not s or
        not s.player or
        not s.map or
        s.player.is_restricted
    ):
        return Response(content=b"error: no")

    if not s.player.privileges & Privileges.VERIFIED:
        return Response(content=b"error: verify")

    if s.mods & Mods.DISABLED:
        return Response(content=b"error: disabled")

    passed = s.status >= SubmitStatus.PASSED
    s.play_time = form["st" if passed else "ft"]
    s.id = await s.save_to_db()

    if passed:
        stats = s.player

        # check if the user is playing the map for the first time
        prev_stats = None

        if stats.total_score > 0:
            prev_stats = copy.copy(stats)

        # save replay
        with open(f".data/replays/{s.id}.osr", "wb+") as file:
            file.write(await form["score"].read())

        # calculate new stats
        if s.map.approved & Approved.HAS_LEADERBOARD:
            # update map passes
            s.map.passes += 1

            # restrict the player if they
            # somehow managed to submit a
            # score without a replay.
            if not form.getlist("score"):
                await s.player.restrict()
                return Response(content=b"error: invalid")

            await services.sql.execute(
                "UPDATE beatmaps SET plays = %s, passes = %s WHERE hash = %s",
                (s.map.plays, s.map.passes, s.map.hash_md5),
            )

            stats.playcount += 1
            stats.total_score += s.score

            if s.status == SubmitStatus.BEST:
                sus = s.score

                if s.pb:
                    sus -= s.pb.score

                stats.ranked_score += sus

                scores = await services.sql.fetchall(
                    "SELECT pp, accuracy FROM scores "
                    "WHERE user_id = %s AND mode = %s "
                    "AND status = 3 AND relax = %s",
                    (stats.id, s.mode.value, s.relax),
                )

                avg_accuracy = np.array([x[1] for x in scores])

                stats.accuracy = float(np.mean(avg_accuracy))

                if s.map.approved & Approved.AWARDS_PP:
                    weighted = np.sum(
                        [
                            score[0] * 0.95 ** (place)
                            for place, score in enumerate(scores)
                        ]
                    )
                    weighted += 416.6667 * (1 - 0.9994 ** len(scores))
                    stats.pp = math.ceil(weighted)

                    stats.rank = await stats.update_rank(s.relax, s.mode) + 1

                await stats.update_stats(s.mode, s.relax)

                # if the player got a position on
                # the leaderboard lower than or equal to 10
                # announce it
                if s.position <= 10 and not stats.is_restricted:
                    chan = services.channels.get("#announce")
                    assert chan is not None

                    await chan.send(
                        f"{s.player.embed} achieved #{s.position} on {s.map.embed} ({s.mode.to_string()}) [{'RX' if s.relax else 'VN'}]",
                        sender=services.bot,
                    )

            _achievements = []
            for ach in services.achievements:
                if ach in stats.achievements:
                    continue

                # if the achievement condition matches
                # with the score, it should be unlocked.
                if eval(ach.condition):
                    await services.sql.execute(
                        "INSERT INTO users_achievements "
                        "(user_id, achievement_id) VALUES (%s, %s)",
                        (stats.id, ach.id),
                    )

                    stats.achievements.add(ach)
                    _achievements.append(ach)

            achievements = "/".join(str(ach) for ach in _achievements)

            log.info(
                f"{stats.username} submitted a score on {s.map.full_title} ({s.mode.to_string()}: {s.pp}pp) [{'RELAX' if s.relax else 'VANILLA'}]"
            )

            # only do charts if the score isn't relax
            # but do charts if the user is playing on rina
            ret: list = []
            if not s.relax and not stats.on_rina:
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
                                    Beatmap.add_chart(
                                        "rank", after=s.position),
                                    Beatmap.add_chart(
                                        "accuracy", after=s.accuracy),
                                    Beatmap.add_chart(
                                        "maxCombo", after=s.max_combo),
                                    Beatmap.add_chart(
                                        "rankedScore", after=s.score),
                                    Beatmap.add_chart(
                                        "totalScore", after=s.score),
                                    Beatmap.add_chart(
                                        "pp", after=math.ceil(s.pp)),
                                )
                                if not s.pb
                                else (
                                    Beatmap.add_chart(
                                        "rank", s.pb.position, s.position
                                    ),
                                    Beatmap.add_chart(
                                        "accuracy", s.pb.accuracy, s.accuracy
                                    ),
                                    Beatmap.add_chart(
                                        "maxCombo", s.pb.max_combo, s.max_combo
                                    ),
                                    Beatmap.add_chart(
                                        "rankedScore", s.pb.score, s.score
                                    ),
                                    Beatmap.add_chart(
                                        "totalScore", s.pb.score, s.score
                                    ),
                                    Beatmap.add_chart(
                                        "pp", math.ceil(
                                            s.pb.pp), math.ceil(s.pp)
                                    ),
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
                                    Beatmap.add_chart(
                                        "rank", after=stats.rank),
                                    Beatmap.add_chart(
                                        "accuracy", after=stats.accuracy),
                                    Beatmap.add_chart("maxCombo", after=0),
                                    Beatmap.add_chart(
                                        "rankedScore", prev=stats.ranked_score
                                    ),
                                    Beatmap.add_chart(
                                        "totalScore", after=stats.total_score
                                    ),
                                    Beatmap.add_chart("pp", after=stats.pp),
                                )
                                if not prev_stats
                                else (
                                    Beatmap.add_chart(
                                        "rank", prev_stats.rank, stats.rank
                                    ),
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
                                    Beatmap.add_chart(
                                        "pp", prev_stats.pp, stats.pp),
                                )
                            ),
                            f"achievements-new:{achievements}",
                        )
                    )
                )

                stats.last_score = s
                return Response(content="\n".join(ret).encode())

            return Response(content=b"error: no")

    return Response(content=b"error: no")


@osu.route("/web/osu-getreplay.php")
@check_auth("u", "h")
async def get_replay(req: Request, p: Player) -> Response:
    if not os.path.isfile((path := f".data/replays/{req.query_params['c']}.osr")):
        log.info(
            f"Replay ID {req.query_params['c']} cannot be loaded! (File not found?)"
        )
        return Response(content=b"")

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
    # TODO: add enums to check abnormal stuff
    if req.query_params["b"][0] == "a":
        return Response(content=b"-3")

    # if nothing odd happens... then keep checking
    return Response(content=b"")


@osu.route("/web/osu-getseasonal.php")
async def get_seasonal(req: Request) -> Response:
    # hmmm... it seems like there's nothing special yet
    # TODO: make a config file for this?
    return Response(content=b"[]")


@osu.route("/web/osu-error.php", methods=["POST"])
async def get_osu_error(req: Request) -> Response:
    # not really our problem though :trolley:
    # let's just send this empty thing
    log.error("osu sent an error")
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
    if os.path.isfile((path := f".data/ss/{req.path_params['ssid']}.png")):
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

    url = f"https://api.nerinyan.moe/search?q={query}&m={mode}&ps=100&s={ranking}{'&sort=updated_desc' if ranking in ('all', 'pending', 'graveyard') else ''}&p={args['p']}"
    bmCount = 0
    directList = ""

    async with aiohttp.ClientSession() as sess:
        async with sess.get(url) as resp:
            if len(await resp.json()) == 100:
                bmCount = 1

            for beatmapsSet in await resp.json():
                bmCount += 1

                sid = beatmapsSet["id"]
                artist = beatmapsSet["artist"]
                title = beatmapsSet["title"]
                creator = beatmapsSet["creator"]
                ranked = beatmapsSet["ranked"]

                lastUpd = beatmapsSet["last_updated"]

                threadId = beatmapsSet["legacy_thread_url"][
                    43:
                ]  # remove osu link and get only id
                hasVideo = "1" if beatmapsSet["video"] else ""
                hasStoryboard = "1" if beatmapsSet["storyboard"] else ""

                directList += f"{sid}.osz|{artist}|{title}|{creator}|{ranked}|"
                directList += (
                    f"10|{lastUpd}|{sid}|{threadId}|{hasVideo}|{hasStoryboard}|0||"
                )

                for i, beatmaps in enumerate(beatmapsSet["beatmaps"]):
                    diffName = beatmaps["version"]
                    starsRating = beatmaps["difficulty_rating"]
                    mode = beatmaps["mode_int"]

                    directList += f"{diffName.replace(',', '').replace('|', 'ǀ')} ★{starsRating}@{mode}"

                    if i < len(beatmapsSet["beatmaps"]) - 1:
                        directList += ","
                    else:
                        directList += "\n"

    return Response(content=str(bmCount).encode() + "\n".encode() + directList.encode())


@osu.route("/web/osu-search-set.php")
@check_auth("u", "h")
async def osu_search_set(req: Request, p: Player) -> Response:
    match req.query_params:
        # There's also "p" (post) and "t" (topic) too, but who uses that in private server?
        case {"s": sid}:  # TODO: Beatmap Set
            bmap = await services.beatmaps.get_by_set_id(sid)
        case {"b": bid}:  # Beatmap ID
            bmap = await services.beatmaps.get_by_map_id(bid)  # type: ignore
        case {"c": hash}:  # Checksum
            bmap = await services.beatmaps.get(hash)  # type: ignore
        case _:
            bmap = None

    if not bmap:  # if beatmap doesn't exists in db then fetch!
        log.fail(
            "/web/osu-search-set.php: Failed to get map (probably doesn't exist)")
        return Response(content=b"xoxo gossip girl")

    return Response(
        content=f"{bmap.set_id}.osz|{bmap.artist}|{bmap.title}|"
        f"{bmap.creator}|{bmap.approved}|{bmap.rating}|"
        f"{bmap.latest_update}|{bmap.set_id}|"
        "0|0|0|0|0".encode()
    )


@osu.route("/d/{map_id:int}")
@osu.route("/d/{map_id:int}n")  # no video
async def download_osz(req: Request) -> Response:
    return RedirectResponse(
        url=f"https://api.nerinyan.moe/d/{req.path_params['map_id']}{'?noVideo=true' if req.url.path[-1] == 'n' else ''}",
        status_code=301,
    )

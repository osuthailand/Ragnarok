from constants.beatmap import Approved
from objects.beatmap import Beatmap
from objects.channel import Channel
from constants.mods import Mods
from objects import services
from utils import log
from objects.score import Score, SubmitStatus
from collections import defaultdict
from constants.player import Privileges
from typing import Callable
from functools import wraps
from utils import general
from urllib.parse import unquote
import numpy as np
import aiofiles
import aiohttp
import math
import os
import copy
import bcrypt
import hashlib
import asyncio

from starlette.routing import Router
from starlette.requests import Request
from starlette.responses import FileResponse, Response, RedirectResponse


def check_auth(u: str, pw: str, cho_auth: bool = False, method="GET"):
    def decorator(cb: Callable) -> Callable:
        @wraps(cb)
        async def wrapper(req, *args, **kwargs):
            if method == "GET":
                player = unquote(req.query_params[u])
                password = req.query_params[pw]
            else:
                form = await req.form()
                player = unquote(form[u])
                password = form[pw]

            if cho_auth:
                if not (
                    user_info := await services.sql.fetch(
                        "SELECT username, id, privileges, "
                        "passhash, lon, lat, country, cc FROM users "
                        "WHERE safe_username = %s",
                        [player.lower().replace(" ", "_")],
                    )
                ):
                    return Response(content=b"")

                phash = user_info["passhash"].encode("utf-8")
                pmd5 = password.encode("utf-8")

                if phash in services.bcrypt_cache:
                    if pmd5 != services.bcrypt_cache[phash]:
                        log.warn(
                            f"USER {user_info['username']} ({user_info['id']}) | Login fail. (WRONG PASSWORD)"
                        )

                        return Response(content=b"")
                else:
                    if not bcrypt.checkpw(pmd5, phash):
                        log.warn(
                            f"USER {user_info['username']} ({user_info['id']}) | Login fail. (WRONG PASSWORD)"
                        )

                        return Response(content=b"")

                    services.bcrypt_cache[phash] = pmd5
            else:
                if not (p := services.players.get(player)):
                    return Response(content=b"")

                if p.passhash in services.bcrypt_cache:
                    if password.encode("utf-8") != services.bcrypt_cache[p.passhash]:
                        return Response(content=b"")

            return await cb(req, *args, **kwargs)

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
        return general.ORJSONResponse(status_code=400, content={"form_error": {"user": error_response}})

    # TODO: website registration config
    #if services.web_register:
        # osu! will attempt to go to https://url?username={username}&email={email}
        #return ORJSONResponse(status_code=403, content={"error":"please register from Rina website","url":"https:\/\/rina.place\/register"}})

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
            # I hope this is legal.
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


@osu.route("/web/osu-osz2-getscores.php")
@check_auth("us", "ha")
async def get_scores(req: Request) -> Response:
    hash = req.query_params["c"]
    mode = int(req.query_params["m"])

    if not hash in services.beatmaps:
        b = await Beatmap.get_beatmap(hash, req.query_params["i"])
    else:
        b = services.beatmaps[hash]

    if not b:
        if not hash in services.beatmaps:
            services.beatmaps[hash] = None

        return Response(content=b"-1|true")

    if b.approved <= Approved.UPDATE:
        if not hash in services.beatmaps:
            services.beatmaps[hash] = b

        return Response(content=f"{b.approved.to_osu}|false".encode())

    # no need for check, as its in the decorator
    if not (p := services.players.get(unquote(req.query_params["us"]))):
        return Response(content=b"what")

    # pretty sus
    if not int(req.query_params["mods"]) & Mods.RELAX and p.relax:
        p.relax = False

    if int(req.query_params["mods"]) & Mods.RELAX and not p.relax:
        p.relax = True

    ret = b.web_format
    order = ("score", "pp")[p.relax]

    if b.approved >= Approved.RANKED:
        if not (
            data := await services.sql.fetch(
                "SELECT id FROM scores WHERE user_id = %s "
                "AND relax = %s AND hash_md5 = %s AND mode = %s "
                f"AND status = 3 ORDER BY {order} DESC LIMIT 1",
                (p.id, p.relax, b.hash_md5, mode),
            )
        ):
            ret += "\n"
        else:
            s = await Score.set_data_from_sql(data["id"])

            ret += s.web_format
            
        async for play in services.sql.iterall(
            "SELECT s.id FROM scores s INNER JOIN users u ON u.id = s.user_id "
            "WHERE s.hash_md5 = %s AND s.mode = %s AND s.relax = %s AND s.status = 3 "
            f"AND u.privileges & 4 ORDER BY s.{order} DESC, s.submitted ASC LIMIT 50",
            (b.hash_md5, mode, p.relax),
        ):
            ls = await Score.set_data_from_sql(play["id"])

            await ls.calculate_position()

            ls.map.scores += 1

            ret += ls.web_format


    asyncio.create_task(save_beatmap_file(b.map_id))

    if not hash in services.beatmaps:
        services.beatmaps[hash] = b

    return Response(content=ret.encode())


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

    if not s or not s.player or not s.map:
        return Response(content=b"error: no")

    if not s.player.privileges & Privileges.VERIFIED:
        return Response(content=b"error: verify")

    if s.mods & Mods.DISABLED:
        return Response(content=b"error: disabled")

    passed = s.status >= SubmitStatus.PASSED
    s.play_time = form["st" if passed else "ft"]

    # handle needed things, if the map is ranked.
    if s.map.approved >= Approved.RANKED:
        if not s.player.is_restricted:
            s.map.plays += 1

            if passed:
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
        if s.map.approved >= Approved.RANKED:
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
                        (stats.id, ach.id)
                    )

                    stats.achievements.add(ach)
                    _achievements.append(ach)

            achievements = "/".join(str(ach) for ach in _achievements)

            stats.playcount += 1
            stats.total_score += s.score

            if s.status == SubmitStatus.BEST:
                sus = s.score

                if s.pb:
                    sus -= s.pb.score

                stats.ranked_score += sus

                # maybe we can cache this?
                scores = await services.sql.fetchall(
                    "SELECT pp, accuracy FROM scores "
                    "WHERE user_id = %s AND mode = %s "
                    "AND status = 3 AND relax = %s",
                    (stats.id, s.mode.value, s.relax),
                )

                avg_accuracy = np.array([x[1] for x in scores])

                stats.accuracy = float(np.mean(avg_accuracy))

                weighted = np.sum(
                    [score[0] * 0.95 ** (place) for place, score in enumerate(scores)]
                )
                weighted += 416.6667 * (1 - 0.9994 ** len(scores))
                stats.pp = math.ceil(weighted)

                stats.rank = await stats.update_rank(s.relax, s.mode) + 1
                await stats.update_stats(s.mode, s.relax)

                # if the player got a position on
                # the leaderboard lower than or equal to 11
                # announce it
                if s.position <= 10 and not stats.is_restricted:
                    modes = {0: "osu!", 1: "osu!taiko", 2: "osu!catch", 3: "osu!mania"}[
                        s.mode.value
                    ]

                    chan: Channel = services.channels.get("#announce")

                    await chan.send(
                        f"{s.player.embed} achieved #{s.position} on {s.map.embed} ({modes}) [{'RX' if s.relax else 'VN'}]",
                        sender=services.bot,
                    )

        # only do charts if the score isn't relax
        if not s.relax:
            ret: list = []

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
                                Beatmap.add_chart(
                                    "accuracy", s.pb.accuracy, s.accuracy
                                ),
                                Beatmap.add_chart(
                                    "maxCombo", s.pb.max_combo, s.max_combo
                                ),
                                Beatmap.add_chart("rankedScore", s.pb.score, s.score),
                                Beatmap.add_chart("totalScore", s.pb.score, s.score),
                                Beatmap.add_chart(
                                    "pp", math.ceil(s.pb.pp), math.ceil(s.pp)
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
                                Beatmap.add_chart("rank", after=stats.rank),
                                Beatmap.add_chart("accuracy", after=stats.accuracy),
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

            stats.last_score = s
        else:
            return Response(content=b"error: no")
    else:
        return Response(content=b"error: no")

    return Response(content="\n".join(ret).encode())


@osu.route("/web/osu-getreplay.php")
@check_auth("u", "h")
async def get_replay(req: Request) -> Response:
    if not os.path.isfile((path := f".data/replays/{req.query_params['c']}.osr")):
        log.info(f"Replay ID {req.query_params['c']} cannot be loaded! (File not found?)")
        return Response(content=b"")

    return FileResponse(path=path)



@osu.route("/web/osu-getfriends.php")
@check_auth("u", "h")
async def get_friends(req: Request) -> Response:
    if not (p := await services.players.get_offline(unquote(req.query_params["u"]))):
        return Response(content="player not found")

    await p.get_friends()

    return Response(content="\n".join(map(str, p.friends)).encode())


@osu.route("/web/osu-markasread.php")
@check_auth("u", "h")
async def markasread(req: Request) -> Response:
    if not (chan := services.channels.get(req.query_params["channel"])):
        return Response(content=b"")

    # TODO: maybe make a mail system???
    return Response(content=b"")


@osu.route("/web/lastfm.php")
@check_auth("us", "ha")
async def lastfm(req: Request) -> Response:
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
    return Response(content=b"")


@osu.route("/web/osu-comment.php", methods=["POST"])
@check_auth("u", "p", method="POST")
async def get_beatmap_comments(req: Request) -> Response:
    return Response(content=b"")


@osu.route("/web/osu-screenshot.php", methods=["POST"])
@check_auth("u", "p", method="POST")
async def post_screenshot(req: Request) -> Response:
    id = general.random_string(8)
    form = await req.form()

    async with aiofiles.open(f".data/ss/{id}.png", "wb+") as ss:
        await ss.write(await form['ss'].read())

    return Response(content=f"{id}.png".encode())


@osu.route("/ss/{ssid:str}.png")
async def get_screenshot(req: Request) -> FileResponse | Response:
    if os.path.isfile((path := f".data/ss/{req.path_params['ssid']}.png")):
        return FileResponse(path=path)

    return Response(content=b"no screenshot with that id.")


@osu.route("/web/osu-search.php")
@check_auth("u", "h")
async def osu_direct(req: Request) -> Response:
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

                threadId = beatmapsSet["legacy_thread_url"][43:] #remove osu link and get only id
                hasVideo = "1" if beatmapsSet["video"] else ""
                hasStoryboard = "1" if beatmapsSet["storyboard"] else ""

                directList += f"{sid}.osz|{artist}|{title}|{creator}|{ranked}|"
                directList += f"10|{lastUpd}|{sid}|{threadId}|{hasVideo}|{hasStoryboard}|0||"

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
async def osu_search_set(req: Request) -> Response:
    match req.query_params:
        # There's also "p" (post) and "t" (topic) too, but who uses that in private server?
        case {"s": sid}: # TODO: Beatmap Set
            return Response(content=b"")
        case {"b": bid}: # Beatmap ID
            bm = bid
            bmap = await Beatmap.get_beatmap(beatmap_id=bm) # type: ignore
        case {"c": hash}: # Checksum
            bm = hash
            bmap = await Beatmap.get_beatmap(hash=bm) # type: ignore
        case _:
            bmap = None

    if not bmap: # if beatmap doesn't exists in db then fetch!
        log.fail("/web/osu-search-set.php: Failed to get map (probably doesn't exist)")

    return Response(content=
        "{bmap.set_id}.osz|{bmap.artist}|{bmap.title}|"
        "{bmap.creator}|{bmap.approved}|{bmap.rating}|"
        "{bmap.latest_update}|{bmap.set_id}|"
        "0|0|0|0|0".encode()
    )


@osu.route("/d/{map_id:int}")
@osu.route("/d/{map_id:int}n") # no video
async def download_osz(req: Request) -> Response:
    return RedirectResponse(
        url=f"https://api.nerinyan.moe/d/{req.path_params['map_id']}{'?noVideo=true' if req.url.path[-1] == 'n' else ''}",
        status_code=301
    )
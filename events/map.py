import hashlib
from objects.OSZ2 import OSZ2
from objects.player import Player

from events.osu import osu, check_auth
from starlette.requests import Request
from starlette.responses import Response
from objects import services
from objects.beatmap import Beatmap

from rina_pp_pyb import Performance, Beatmap as BMap


@osu.route("/web/osu-osz2-bmsubmit-getid.php")
@check_auth("u", "h", b"5\nAuthentication failure. Please check your login details.")
async def get_last_id(request: Request, player: Player) -> Response:
    # arguments:
    # s = BeatmapSetId (if available)
    # b = BeatmapIds (comma separated list)
    # z = Osz2Hash (if available)

    """
    error codes (if value more than 4 will display custom error dialog):
    1 - This beatmap you're trying to submit isn't yours!
    3 - This beatmap is already ranked. You cannot update ranked maps.
    4 - This beatmap is currently in the beatmap graveyard. You can ungraveyard your map by visiting the beatmaps section of your profile on the osu! website.
        PS. This seems to be unused now after bancho updated their beatmap system.
    5 - Auth failure/Restricted
    6 - You have exceeded your submission cap (you are currently allowed {placeholder} total unranked maps). Please finish the maps you have currently submitted, or wait until your submissions expire automatically to the graveyarded (~4weeks).
    0 - Update successful
    -2 - A server-side error occurred. Please try again later
    -3 - The package uploaded seems to be corrupted. Please try once more to fix this
    -4 - The metadata could not be updated
    -5 - Could not copy to the destination mappackage
    -6 - The requested download part is out of bounds
    -7 - The requested download part is out of bounds
    everything else - Unknown error occured
    """

    if player.is_restricted:
        return Response(content=b"5\nYour account is currently restricted.")

    BASE_ID_INCREMENT = 100_000_000

    if player.id not in (1000, 1106):
        return Response(content=b"6\nNo permission to upload (yet)")

    await player.update_latest_activity()

    set_id = int(request.query_params["s"])
    services.logger.debug(set_id)
    map_ids = request.query_params["b"].split(",")
    old_osz2_hash = request.query_params["z"]

    new_submit = old_osz2_hash == ""
    osz2_available = False

    if set_id < BASE_ID_INCREMENT and set_id != -1:
        return Response(
            content=b"7\nYou're not allowed to update bancho maps. (error 1)"
        )

    # check if penis map exist in database
    # also check if the set_id is below base_id_increment
    # (that would mean it's not from rina)
    map = await services.database.fetch_one(
        "SELECT server, creator_id FROM beatmaps " "WHERE set_id = :set_id LIMIT 1",
        {"set_id": set_id},
    )

    if map:
        # if this beatmap is already in the system/existed
        if map["server"] == "bancho":
            return Response(
                content=b"7\nYou're not allowed to update bancho maps. (error 2)"
            )

        if map["creator_id"] != player.id:
            return Response(
                content=b"1\nThe beatmap you're trying to submit isn't yours!"
            )

    # return Response(
    #     content=b"-2\nUpdating beatmaps upon submission is not supported yet."
    # )

    if new_submit:
        # if there are no set ids that is over the base set id increment
        # it's the first ever custom submited map.
        if not (
            latest_submitted_set_id := await services.database.fetch_one(
                "SELECT set_id FROM beatmaps WHERE set_id >= :increment ORDER BY set_id DESC LIMIT 1",
                {"increment": BASE_ID_INCREMENT},
            )
        ):
            set_id = BASE_ID_INCREMENT
        else:
            set_id = latest_submitted_set_id["set_id"] + 1

        latest_submitted_map_id = await services.database.fetch_one(
            "SELECT map_id FROM beatmaps WHERE map_id >= :increment ORDER BY map_id DESC LIMIT 1",
            {"increment": BASE_ID_INCREMENT},
        )

        if not latest_submitted_map_id:
            latest_submitted_map_id = [
                BASE_ID_INCREMENT
            ]  # we make it a list, so we can do [0]

        idx = 0
        while idx < len(map_ids):
            map_ids[idx] = str(latest_submitted_map_id[0] + idx + 1)
            idx += 1

    # If everything went well, prepare for a new submission.
    res: list[str] = []

    res.append("0")  # response (0 = success, >0 = error)
    res.append(str(set_id))  # new set id
    res.append(",".join(map_ids))
    # osu client only checks if full submit is equal to 1.
    res.append(
        "1"
        if new_submit
        else "2"  # 1 = full beatmap submission, X = ready to update/"patch-submit"
    )
    res.append("1337")  # upload cpa
    res.append(
        "0"
    )  # 0 = Pending, -2 = Un-graveyard, something else that is not 0 = WIP
    res.append("0")  # unused since 2017
    res.append("0")  # make this 0 to disable browser popup by default
    return Response(content="\n".join(res).encode())


@osu.route("/web/osu-get-beatmap-topic.php")
@check_auth("u", "h")
async def get_beatmap_topic(req: Request, p: Player) -> Response:
    # don't really know if this is nessecairyefoiweuijfjipenis
    res = ["0"]  # 0 = success, >0 = error
    res.append("1")  # thread id
    res.append("2")  # thread subject
    res.append(
        "this feature is not implemented, no reason to write anything..."
    )  # thead contents
    return Response(content="\u0003".join(res).encode())


@osu.route("/web/osu-osz2-bmsubmit-upload.php", methods=["POST"])
@check_auth("u", "h", method="POST")
async def beatmap_submission(req: Request, p: Player) -> Response:
    form = await req.form()
    data = await form["osz2"].read()  # type: ignore
    set_id = form["s"]
    patch = form["t"] == "2"

    with open(f".data/osz2/{"PATCHED_" if patch else ""}{set_id}.osz2", "wb+") as osz2:
        osz2.write(data)

    if not (osz2_data := OSZ2.parse(raw=data, file_type=int(form["t"]))):  # type: ignore
        return Response(content=b"error while parsing osz2")

    set_id = form["s"]
    maps = osz2_data.extract_osu_files()
    metadata = osz2_data.metadata

    for child_map in maps:
        # TODO: .osu parser specifically made for this, instead of using external libraries
        attributes = BMap(bytes=child_map.raw_data)
        difficulty = Performance().calculate(attributes).difficulty

        map = await services.beatmaps.get_by_map_id(child_map._map_id) or Beatmap()

        map.server = "rina"
        map.title = metadata.title
        map.artist = metadata.artist

        osu_file_regex = services.regex[".osu"].search(child_map.name)

        if not osu_file_regex:
            return Response(content=b"Unexpected error.")

        map.artist = osu_file_regex.group(1)
        map.artist_unicode = metadata.artist_unicode

        map.title = osu_file_regex.group(2)
        map.title_unicode = metadata.title_unicode

        map.version = osu_file_regex.group(4)

        map.creator = p.username
        map.creator_id = p.id

        map.set_id = metadata.set_id
        map.map_id = child_map._map_id

        map.ar = attributes.ar
        map.od = attributes.od
        map.hp = attributes.hp
        map.cs = attributes.cs
        map.bpm = attributes.bpm
        map.mode = attributes.mode.value

        map.stars = difficulty.stars
        map.max_combo = difficulty.max_combo
        map.map_md5 = hashlib.md5(child_map.raw_data).digest().hex()

        # TODO: proper beatmap update
        if old_map := await services.database.fetch_one(
            "SELECT map_md5 FROM beatmaps WHERE map_id = :map_id",
            {"map_id": map.map_id},
        ):
            await services.database.execute(
                "DELETE FROM beatmaps WHERE map_md5 = :map_md5",
                {"map_md5": old_map["map_md5"]},
            )

        await map.add_to_db()

        # save .osu file in .data/beatmaps
        with open(f".data/beatmaps/{map.map_id}.osu", "wb+") as osu_file:
            osu_file.write(child_map.raw_data)

    # response with "0" if everything went right, okay
    return Response(content=b"0")

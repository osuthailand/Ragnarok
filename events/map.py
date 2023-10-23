from objects.OSZ2 import OSZ2
from objects.player import Player
from utils import log
from events.osu import osu, check_auth
from constants.beatmap import Approved
from urllib.parse import unquote
from urllib.parse import unquote
from starlette.requests import Request
from starlette.responses import Response
from objects import services

@osu.route("/web/osu-osz2-bmsubmit-getid.php")
@check_auth(
    "u", "h", b"5\nAuthentication failure. Please check your login details."
)
async def get_last_id(req: Request, p: Player) -> Response:
    # arguments:
    # s = BeatmapSetId (if available)
    # b = BeatmapIds (comma separated list)
    # z = Osz2Hash (if available)

    """
    error codes (if value more than 4 will display custom error dialog.):
    1 - This beatmap you're trying to submit isn't yours!
    3 - This beatmap is already ranked. You cannot update ranked maps.
    4 - This beatmap is currently in the beatmap graveyard. You can ungraveyard your map by visiting the beatmaps section of your profile on the osu! website.
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

    BASE_ID_INCREMENT = 100_000_000

    if not (p := await services.players.get_offline(unquote(req.query_params["u"]))):
        return Response(content=b"5\nUser not found in system")
    
    if p.username not in ("Aoba", "real"):
        return Response(content=b"6\nNo permission to upload (yet)")

    set_id = int(req.query_params["s"])
    map_ids = req.query_params["b"].split(",")
    oldOsz2Hash = req.query_params["z"]

    creatorId = -1
    new_submit = True
    osz2_available = False

    upload_cap = 1337  # placeholder

    # if this beatmap is already in the system/existed
    if set_id > 0:
        new_submit = False
        # check if penis map even exist in database
        # also check if the set_id is below base_id_increment
        # (that would mean it's not from rina)
        if set_id < BASE_ID_INCREMENT and not await services.sql.fetch(
            "SELECT 1 FROM beatmaps WHERE set_id = %s", (set_id)
        ):
            new_submit = True
            set_id = -1

        # disable this until testing is done
        # if p.id != creatorId:
        #     # TODO: maybe allow administrators to submit maps as somebody else?
        #     return Response(content=b"1\n")

        # if set_id < 100_000_000:
        #     return Response(content=b"6\nBeatmap is already on Bancho!")

        # if custom_beatmap is ranked:
        #   return Response(content=b"3\n")

        # if custom_beatmap is inactive:
        #   return Response(content=b"4\n")
    # set_id = -1 then its a new beatmap
    # else:
    # set_id = beatmap.insert_new_custom_map(p.id, p.username)
    if new_submit:
        if not (
            latest_submitted_map_id := await services.sql.fetch(
                "SELECT set_id FROM beatmaps WHERE set_id > %s ORDER BY set_id DESC LIMIT 1",
                (BASE_ID_INCREMENT),
            )
        ):
            set_id = BASE_ID_INCREMENT
        else:
            set_id = latest_submitted_map_id["set_id"] + 1

    # If everything went well, prepare for a new submission.
    res: list[str] = []

    res.append("0")  # response (0 = success, >0 = error)

    res.append(str(set_id))  # new set id
    res.append(",".join(map_ids))

    # osu client only checks if full submit is equal to 1.
    res.append(
        "1" if new_submit else "2"
    )  # 1 = full beatmap submission, X = ready to update/"patch-submit"

    res.append("1337")
    res.append("0")  # 0 = WIP, 1 = Pending
    # somwhow this got emptied out when submitting new beatmap on bancho
    res.append("0")  # Approved.GRAVEYARD
    res.append("1")  # add to watchlist, if not then just remove
    return Response(content="\n".join(res).encode())


@osu.route("/web/osu-get-beatmap-topic.php")
@check_auth("u", "h")
async def get_beatmap_topic(req: Request, p: Player) -> Response:
    # don't really know if this is nessecairyefoiweuijfjipenis
    res = ["0"]  # 0 = success, >0 = error
    res.append("1")  # thread id
    res.append("2")  # thread subject
    res.append("luder dreng")  # thead contents
    return Response(content="\u0003".join(res).encode())


@osu.route("/web/osu-osz2-bmsubmit-upload.php", methods=["POST"])
#@check_auth("u", "h")
async def beatmap_submission(req: Request) -> Response:
    form = await req.form()

    set_id = form["s"]
    with open(f".data/osz2/{set_id}.osz2", "wb+") as osz2:
        data = await form["osz2"].read()
        osz2.write(data)
        OSZ2.parse(raw=data)

    # response with "0" if everything went right, okay
    return Response(content=b"hej mor")

# # from anticheat.utils.beatmap import Beatmap
# # from osrparse import Replay
# # from constants.mods import Mods
# # from utils.replay import write_replay
# # from constants.playmode import Mode

# from circleguard import Circleguard, ReplayPath, ReplayString, Slider
# from typing import TYPE_CHECKING

# import numpy
# from constants.anticheat import BadFlags
# from constants.playmode import Gamemode

# from objects import services

# if TYPE_CHECKING:
#     from objects.score import Score


# from objects.player import Player
# from objects.score import Score
# from packets import writer
# from objects import services
# from hashlib import md5
# import aiofiles
# import struct


# # where is this used?
# def _write_replay(s: Score, replay: bytes) -> bytearray:
#     r_hash = md5(
#         f"{s.count_100 + s.count_300}o{s.count_50}o{s.count_geki}o"
#         f"{s.count_katu}t{s.count_miss}a{s.map.map_md5}r{s.max_combo}e"
#         f"{bool(s.perfect)}y{s.player.username}o{s.score}u{s.rank}{s.mods}True".encode()
#     ).hexdigest()

#     ret = bytearray()

#     ret += struct.pack("<b", s.mode)
#     ret += writer.write_int32(
#         20210520
#     )  # we just gonna use the latest version of osu (this is no longer the latest version...)

#     ret += (
#         writer.write_str(s.map.map_md5)
#         + writer.write_str(s.player.username)
#         + writer.write_str(r_hash)
#     )

#     ret += struct.pack(
#         "<hhhhhhih?i",
#         s.count_300,
#         s.count_100,
#         s.count_50,
#         s.count_geki,
#         s.count_katu,
#         s.count_miss,
#         s.score,
#         s.max_combo,
#         s.perfect,
#         s.mods,
#     )

#     ret += writer.write_str("")

#     ret += struct.pack("<qi", s.submitted, len(replay))
#     ret += replay

#     ret += struct.pack("<q", s.id)

#     return ret

# # forget this
# async def run(score: "Score", replay: bytes):
#     cg = Circleguard(services.config["api_conf"]["osu_api_key"])
#     replay = ReplayString(_write_replay(score, replay))

#     if relax_resp := await relax_check(cg, replay, score):
#         await services.bot.anticheat_log(
#             score, BadFlags.RELAX, description=" ".join(relax_resp)
#         )

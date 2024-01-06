from objects import services
from constants.playmode import Mode


def calculate_accuracy(
    mode: Mode,
    count_300: int,
    count_100: int,
    count_50: int,
    count_geki: int,
    count_katu: int,
    count_miss: int,
) -> float:
    if mode not in (Mode.OSU, Mode.TAIKO, Mode.CATCH, Mode.MANIA):
        return 0.0

    match mode:
        case Mode.OSU:
            services.logger.debug("Calculating accuracy for standard")

            acc = (50 * count_50 + 100 * count_100 + 300 * count_300) / (
                300 * (count_miss + count_50 + count_100 + count_300)
            )
        case Mode.TAIKO:
            services.logger.debug("Calculating accuracy for taiko")

            acc = (0.5 * count_100 + count_300) / (count_miss + count_100 + count_300)
        case Mode.CATCH:
            services.logger.debug("Calculating accuracy for catch the beat")

            acc = (count_50 + count_100 + count_300) / (
                count_katu + count_miss + count_50 + count_100 + count_300
            )
        case Mode.MANIA:
            services.logger.debug("Calculating accuracy for mania")

            acc = (
                50 * count_50
                + 100 * count_100
                + 200 * count_katu
                + 300 * (count_300 + count_geki)
            ) / (
                300
                * (
                    count_miss
                    + count_50
                    + count_100
                    + count_katu
                    + count_300
                    + count_geki
                )
            )
        case _:
            services.logger.critical(f"mode {mode} doesn't exist.")
            return 0

    return acc * 100

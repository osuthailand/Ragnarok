conf = {
    "server": {"debug": False, "domain": "YOUR.DOMAIN", "port": 8000},
    "mysql": {
        "host": "localhost",
        "user": "CHANGE THIS",
        "password": "CHANGE THIS",
        "db": "CHANGE THIS",
        "autocommit": True,
    },
    "redis": {
        "host": "localhost",
        "username": "CHANGE THIS IF ANYTHING",
        "password": "CHANGE THIS IF ANYTHING",
        "port": 6379,
    },
    "api_conf": {
        "osu_api_key": "CHANGE THIS",
        "mirrors": {
            "chimu": "https://api.chimu.moe/v1/",
            "katsu": "https://katsu.moe/",
        },
    },
    "fun": {"rank_all_maps": False},
}

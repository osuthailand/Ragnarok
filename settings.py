import os

from dotenv import load_dotenv

load_dotenv()

SERVER_DEBUG = os.environ["SERVER_DEBUG"]
SERVER_DOMAIN = os.environ["SERVER_DOMAIN"]
SERVER_PORT = os.environ["SERVER_PORT"]

DB_HOST = os.environ["DB_HOST"]
DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]
DB_DATABASE = os.environ["DB_DATABASE"]

REDIS_USERNAME = os.environ["REDIS_USERNAME"]
REDIS_PASSWORD = os.environ["REDIS_PASSWORD"]
REDIS_HOST = os.environ["REDIS_HOST"]
REDIS_PORT = os.environ["REDIS_PORT"]

OSU_API_KEY = os.environ["OSU_API_KEY"]

MIRROR_CHIMU = os.environ["MIRROR_CHIMU"]
MIRROR_KATSU = os.environ["MIRROR_KATSU"]
MIRROR_NERINYAN = os.environ["MIRROR_NERINYAN"]

RANK_ALL_MAPS = os.environ["RANK_ALL_MAPS"] == "true"

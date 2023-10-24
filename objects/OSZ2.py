from base64 import b64decode

from dataclasses import dataclass
from enum import IntEnum, unique
from typing import Union
import hashlib
import os
import io

from packets.reader import Reader
from datetime import datetime

from objects.xxtea import decrypt

from struct import pack

from utils import log

@unique
class MetadataType(IntEnum):
    Title = 0
    Artist = 1
    Creator = 2
    Version = 3
    Source = 4
    Tags = 5
    VideoDataOffset = 6
    VideoDataLength = 7
    VideoHash = 8
    BeatmapSetID = 9
    Genre = 10
    Language = 11
    TitleUnicode = 12
    ArtistUnicode = 13
    Difficulty = 14
    PreviewTime = 15
    ArtistFullName = 16
    ArtistTwitter = 17
    SourceUnicode = 18
    ArtistUrl = 19
    Revision = 20
    PackId = 21


@dataclass
class Metadata:
    title: str = ""
    creator: str = ""
    artist: str = ""
    version: str = ""
    set_id: int = 0


@dataclass
class FileInfo:
    Name: str
    Offset: int
    Size: int
    Hash: list[bytes]
    Created: datetime
    Modified: datetime


# fmt: off
# KEY: bytearray = (
#     216, 98, 163, 48, 2,
#     109, 118, 89, 244, 247,
#     37, 194, 235, 70, 174,
#     52, 13, 106, 97, 84, 242,
#     62, 186, 48, 25, 66, 72,
#     85, 242, 22, 15, 92,
# ) # type: ignore
# fmt: on

# fmt: off
# this is FastRandom(1990)
knownByteSeq = bytearray([
   0x55, 0xAA, 0x74, 0x10, 0x2B, 0x56, 0xB3, 0x9E,
   0x25, 0x9E, 0xFE, 0xB7, 0xBE, 0x06, 0xFC, 0xF2,
   0xB6, 0x3C, 0x6F, 0x47, 0x7E, 0x38, 0x69, 0x43,
   0x80, 0x89, 0x25, 0x00, 0xCC, 0xB6, 0xFE, 0x12,
   0xA9, 0xB2, 0x4A, 0x2C, 0x96, 0xD5, 0xEA, 0x26,
   0x42, 0x31, 0xAF, 0x0A, 0x0D, 0xAE, 0x00, 0xED,
   0xFE, 0x96, 0xA6, 0x94, 0x99, 0xA7, 0x90, 0xE4,
   0x68, 0xBF, 0xC6, 0x97, 0x5B, 0x1B, 0x5E, 0x7F
])
# fmt: on

# lol
KNOWN_PLAIN = bytearray(64)


def bytes_to_vector(b: bytearray):
    return [
        int.from_bytes(b[:4], byteorder="big"),
        int.from_bytes(b[4:8], byteorder="big"),
    ]

# FastRandom(1990)
def generate_known_plain() -> bytearray:
    b = bytearray(64)

    y = 842502087
    x = 1990 # Seed for XTEA verification
    w = 273326509
    z = 3579807591

    t = 0
    i = 0
    while i < len(b) - 3:
        t = x ^ (x << 11)

        x = y
        y = z
        z = w
        w = (w ^ (w >> 19)) ^ (t ^ (t >> 8))

        b[i] = w & 0x000000FF
        b[i + 1] = (w & 0x0000FF00) >> 8
        b[i + 2] = (w & 0x00FF0000) >> 16
        b[i + 3] = (w & 0xFF000000) >> 24

        i += 4

    if i < len(b):
        t = x ^ (x << 11)
        x = y
        y = z
        z = w
        w = (w ^ (w >> 19)) ^ (t ^ (t >> 8))

        b[i] = w & 0x000000FF
        i += 1
        if i < len(b):
            b[i] = (w & 0x0000FF00) >> 8
            i += 1
            if i < len(b):
                b[i] = (w & 0x00FF0000) >> 16
                i += 1
                if i < len(b):
                    i += 1
                    b[i] = (w & 0xFF000000) >> 24

    return b

#Just a wrapper class that logs all operations.
class BytesIOWrapper(io.BytesIO):
    def read(self, __size: int | None = None) -> bytes:
        log.debug(f"Reading {__size} bytes")
        return super().read(__size)

    def write(self, __buffer) -> int:
        log.debug(f"Writing {len(__buffer)} bytes")
        return super().write(__buffer)

    def seek(self, __offset: int, __whence: int = 0) -> int:
        log.debug(f"Seeking by {__offset} from {__whence}")
        newPos = super().seek(__offset, __whence)
        log.debug(f"Seeked to {newPos}")
        return newPos

    def tell(self) -> int:
        curPos = super().tell()
        log.debug(f"Telling current position: {curPos}")
        return curPos

class OSZ2:
    def __init__(self) -> None:
        self.metadata: Metadata = Metadata()
        self.files: FileInfo

        self._raw: bytes = b""

    @classmethod
    def parse(cls, filepath: str = "", raw: bytes = b"") -> "OSZ2":
        c = cls()
        data = raw

        if filepath:
            if not os.path.exists(filepath):
                return

            with open(filepath, "rb") as osz2:
                data = osz2.read()

        reader = Reader(data)

        # the file should start with 0xEC, 0x48 and 0x4F otherwise it is NOT osz2
        if reader.read_bytes(3) != (0xEC, 0x48, 0x4F):
            log.fail("User tried to submit an invalid osz2 file")
            return

        version = reader.read_byte()
        iv = bytearray(reader.read_bytes(16))
        oszhash_meta = reader.read_bytes(16)
        oszhash_file = reader.read_bytes(16)
        oszhash_data = reader.read_bytes(16)

        # metadata block
        writerMetaHash = BytesIOWrapper()
        #metadata_entries = reader.read_int32()
        metadata_entries_bytes = reader.read_bytes(4) #i32
        writerMetaHash.write(pack('4B', *metadata_entries_bytes)) # save buffer for verification

        metadata_entries = int.from_bytes(pack('4B', *metadata_entries_bytes), byteorder='little')

        metadata_info = []
        for _ in range(metadata_entries):
            #type = reader.read_int16()
            type_bytes = reader.read_bytes(2) #i16
            value = reader.read_str(retarded=True)

            type = int.from_bytes(type_bytes, byteorder='little')

            log.debug(type)
            log.debug(value)

            match MetadataType(type):
                case MetadataType.Creator:
                    c.metadata.creator = value

                case MetadataType.Artist:
                    c.metadata.artist = value

                case MetadataType.Title:
                    c.metadata.title = value

                case MetadataType.Version:
                    c.metadata.version = value

                case MetadataType.BeatmapSetID:
                    c.metadata.set_id = int(value)

            writerMetaHash.write(pack('2B', *type_bytes))
            writerMetaHash.write((len(str(value).encode('utf-8'))).to_bytes(1, 'little') + str(value).encode()) #shouldve used write_str but er

        # verify if hash is matched with what osz2 reported
        with writerMetaHash.getbuffer() as buffer:
            calculated_oszhash_meta = OSZ2().compute_osz_hash(buffer, metadata_entries * 3, 0xa7)
            if calculated_oszhash_meta != pack('16B', *oszhash_meta):
                log.fail(f"calculated: {calculated_oszhash_meta.hex()}")
                log.fail(f"osz2 report: {pack('16B', *oszhash_meta).hex()}")
                log.fail("bad hashes")
                return

        log.debug(c.metadata)

        num_files = reader.read_int32()

        for _ in range(num_files):
            fileName = reader.read_str(retarded=True)
            map_id = reader.read_int32()

            log.debug(f"{fileName=} {map_id=}")

        # prepare key
        seed = f"{c.metadata.creator}yhxyfjo5{c.metadata.set_id}"
        log.debug(f"{seed=}")

        # save key for later uses
        KEY = hashlib.md5(seed.encode("ascii")).digest()

        # TODO: Verify this magic block using XTEA
        reader.read_bytes(64)

        # read encrypted data length and decrypt it
        length = reader.read_int32()
        for i in range(0, 16, 2):
            length -= oszhash_file[i] | (oszhash_file[i + 1] << 17)

        # read all .osu files in osz2 and set an offset
        fileInfo = reader.read_bytes(length)
        fileOffset = reader.offset

        log.debug(f"{fileInfo=}")
        log.debug(f"{fileOffset=}")

        # prepare the buffer for XXTEA verification and extraction
        fileInfoBytes = bytearray(fileInfo)
        enc_fileInfo_count = fileInfoBytes[0:4]
        enc_fileInfo_offset = fileInfoBytes[4:8]
        log.debug(enc_fileInfo_count)
        log.debug(enc_fileInfo_offset)

        # start decrypting
        fileInfo_count = Reader(decrypt(enc_fileInfo_count, KEY)).read_int32()
        fileInfo_offset = Reader(decrypt(enc_fileInfo_offset, KEY)).read_int32()

        # TODO: make oszhash_file checksum test
        # calculated_oszhash_file = OSZ2().compute_osz_hash(fileInfoBytes, fileInfo_count * 4, 0xd1)
        # if calculated_oszhash_file != pack('16B', *oszhash_file):
        #     log.fail(f"calculated: {calculated_oszhash_file.hex()}")
        #     log.fail(f"osz2 report: {pack('16B', *oszhash_file).hex()}")
        #     log.fail("bad hashes")
        #     return

        # intialize buffer and extract files info
        fileInfo_next_byte = 8
        for _ in range(fileInfo_count):
            log.fail(fileInfo_next_byte)
            # file name
            file_name_len = Reader(decrypt(fileInfoBytes[fileInfo_next_byte:fileInfo_next_byte+1], KEY)).read_byte()
            fileInfo_next_byte = fileInfo_next_byte+1
            file_name_enc = fileInfoBytes[fileInfo_next_byte:(fileInfo_next_byte)+file_name_len]
            file_name_dec = decrypt(file_name_enc, KEY)
            log.debug(f'{file_name_dec=}')

            # file checksum (somehow this always wrong? but eh whatever)
            file_cksm_hash_bytes = fileInfoBytes[fileInfo_next_byte+file_name_len:(fileInfo_next_byte+file_name_len)+16]
            file_hash = Reader(decrypt(file_cksm_hash_bytes, KEY)).read_bytes(16)
            log.debug(f'{bytes(file_hash).hex()=}')
            fileInfo_next_byte = (fileInfo_next_byte) + 16

            # file datetime created/modified (i dont care tbh)
            file_date_created = Reader(decrypt(fileInfoBytes[fileInfo_next_byte+file_name_len:(fileInfo_next_byte+file_name_len)+8], KEY)).read_int64()
            log.debug(f'{file_date_created=}')
            fileInfo_next_byte = (fileInfo_next_byte) + 8
            log.debug(fileInfoBytes[fileInfo_next_byte+file_name_len:(fileInfo_next_byte+file_name_len)+8].hex())
            file_date_modified = Reader(decrypt(fileInfoBytes[fileInfo_next_byte+file_name_len:(fileInfo_next_byte+file_name_len)+8], KEY)).read_int64()
            log.debug(f'{file_date_modified=}')
            fileInfo_next_byte = (fileInfo_next_byte) + 8

            #prep new offset
            next_file_info_offset = 0
            if (_ + 1 < fileInfo_count):
                next_file_info_offset = Reader(decrypt(fileInfoBytes[fileInfo_next_byte+file_name_len:(fileInfo_next_byte+file_name_len)+4], KEY)).read_int32()
                log.debug(next_file_info_offset)
                fileInfo_next_byte = (fileInfo_next_byte+file_name_len) + 4
            else:
                next_file_info_offset = len(data) - fileOffset

            fileLength = next_file_info_offset - fileInfo_offset
            fileInfo_offset = next_file_info_offset

        return c

    @staticmethod
    def compute_osz_hash(buffer: Union[memoryview, bytearray], pos: int, swap: int) -> bytes:
        buffer[pos] ^= swap
        hash = bytearray(hashlib.md5(buffer).digest())
        buffer[pos] ^= swap

        for i in range(8):
            tmp = hash[i]
            hash[i] = hash[i + 8]
            hash[i + 8] = tmp

        hash[5] ^= 0x2d

        return bytes(hash)
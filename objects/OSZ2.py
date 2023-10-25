from base64 import b64decode

from dataclasses import dataclass
from enum import IntEnum, unique
import struct
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


class DecryptReader:
    def __init__(self, data, key: bytes) -> None:
        self.key: bytes = key
        self._data = memoryview(bytearray(data))
        self.offset: int = 0

    @property
    def data(self):
        return self._data[self.offset:]

    def __enter__(self):
        return self, self._data

    def __exit__(self, exc_type, exc_value, traceback):
        pass

    def read_bytes(self, size: int):
        dec = decrypt(self.data[:size], self.key)
        self.offset += size
        return struct.unpack(f"<{"B"*size}", dec)

    def read_byte(self) -> int:
        ret = struct.unpack("<b", decrypt(self.data[:1], self.key))
        self.offset += 1
        return ret[0]

    def read_int32(self) -> int:
        ret = int.from_bytes(
            decrypt(self.data[:4], self.key), "little", signed=True)
        self.offset += 4
        return ret

    def read_int64(self) -> int:
        ret = int.from_bytes(
            decrypt(self.data[:8], self.key), "little", signed=True)
        self.offset += 8
        return ret

    def read_str(self, known_length: int) -> str:
        data = decrypt(self.data[: known_length], self.key)

        shift = 0
        result = 0

        while True:
            b = data[0]
            self.offset += 1

            result |= (b & 0x7F) << shift

            if b & 0x80 == 0:
                break

            shift += 7

        ret = data[:known_length].decode()

        self.offset += known_length
        return ret


class BytesIOWrapper(io.BytesIO):
    def read(self, __size: int | None = None) -> bytes:
        return super().read(__size)

    def write(self, __buffer) -> int:
        return super().write(__buffer)

    def seek(self, __offset: int, __whence: int = 0) -> int:
        newPos = super().seek(__offset, __whence)
        return newPos

    def tell(self) -> int:
        curPos = super().tell()
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
                log.fail("The osz2 doesn't exist[]")
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
        hash_meta = reader.read_bytes(16)
        hash_file = reader.read_bytes(16)
        hash_data = reader.read_bytes(16)

        # metadata block
        writerMetaHash = BytesIOWrapper()
        # metadata_entries = reader.read_int32()
        metadata_entries_bytes = reader.read_bytes(4)  # i32
        # save buffer for verification
        writerMetaHash.write(pack('4B', *metadata_entries_bytes))

        metadata_entries = int.from_bytes(
            pack('4B', *metadata_entries_bytes), byteorder='little')

        metadata_info = []
        for _ in range(metadata_entries):
            # type = reader.read_int16()
            type_bytes = reader.read_bytes(2)  # i16
            value = reader.read_str(retarded=True)

            type = int.from_bytes(type_bytes, byteorder='little')

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
            writerMetaHash.write((len(str(value).encode('utf-8'))).to_bytes(
                # shouldve used write_str but er
                1, 'little') + str(value).encode())

        # verify if hash is matched with what osz2 reported
        with writerMetaHash.getbuffer() as buffer:
            calculated_hash_meta = OSZ2().compute_osz_hash(
                buffer, metadata_entries * 3, 0xa7)
            if calculated_hash_meta != pack('16B', *hash_meta):
                log.fail(f"calculated: {calculated_hash_meta.hex()}")
                log.fail(f"osz2 report: {pack('16B', *hash_meta).hex()}")
                log.fail("bad hashes")
                return

        num_files = reader.read_int32()

        for _ in range(num_files):
            fileName = reader.read_str(retarded=True)
            map_id = reader.read_int32()

        # prepare key
        seed = f"{c.metadata.creator}yhxyfjo5{c.metadata.set_id}"

        # save key for later uses
        KEY = hashlib.md5(seed.encode("ascii")).digest()

        # TODO: Verify this magic block using XTEA
        reader.read_bytes(64)  # skip for now

        # read encrypted data length and decrypt it
        length = reader.read_int32()
        for i in range(0, 16, 2):
            length -= hash_file[i] | (hash_file[i + 1] << 17)

        # read all .osu files in osz2 and set an offset
        file_info = reader.read_bytes(length)
        file_offset = reader.offset

        with DecryptReader(file_info, KEY) as (reader, raw_data):
            # prepare the buffer for XXTEA files verification and extraction
            file_info_count = reader.read_int32()
            file_info_offset = reader.read_int32()
            log.debug(f"{file_info_count=}")
            log.debug(f"{file_info_offset=}")
            # verify if hash is matched with what osz2 reported
            # calculated_hash_file = OSZ2.compute_osz_hash(
            #     raw_data, file_info_count * 4, 0xd1)

            # if calculated_hash_file != pack('16B', *hash_file):
            #     log.fail(f"calculated: {calculated_hash_file.hex()}")
            #     log.fail(f"osz2 report: {pack('16B', *hash_file).hex()}")
            #     log.fail("bad hashes")
            #     return

            # intialize buffer and extract files info
            for i in range(file_info_count):
                # file name (get length)
                file_name_len = reader.read_byte()
                log.debug(f"{file_name_len=}")

                # file name (get string)
                # file_name = reader.read_str(file_name_len)
                file_name = (file_name_len.to_bytes(
                    1, "little") + decrypt(reader.data[:file_name_len], KEY)).decode()
                reader.offset += file_name_len

                # file checksum
                file_hash = reader.read_bytes(16)

                # file datetime created/modified
                # TODO: Make this readable by datetime
                file_date_created = reader.read_int64()
                file_date_modified = reader.read_int64()

                # # # prep new offset for files extraction
                next_file_info_offset = 0
                if (i + 1 < file_info_count):
                    # next file is not being used for the rest of the thingy thing thing
                    next_file_info_offset = reader.read_int32()
                    # some_function_that_uses_FileInfo_dataclass_here()
                else:
                    next_file_info_offset = len(raw_data) - file_offset

                file_info = next_file_info_offset - file_info_offset
                file_info_offset = next_file_info_offset

        return c

    @staticmethod
    def compute_osz_hash(buffer: memoryview | bytearray, pos: int, swap: int) -> bytes:
        buffer[pos] ^= swap
        hash = bytearray(hashlib.md5(buffer).digest())
        buffer[pos] ^= swap

        for i in range(8):
            tmp = hash[i]
            hash[i] = hash[i + 8]
            hash[i + 8] = tmp

        hash[5] ^= 0x2d

        return bytes(hash)

from dataclasses import dataclass
from enum import IntEnum, unique
from typing import Union
import zipfile
import struct
import hashlib
import gzip
import os
import io

from packets.reader import Reader
from datetime import datetime
from utils.general import datetime_frombinary

from objects.xxtea import xxtea_decrypt, xtea_decrypt
from objects import services
from struct import pack


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
    title_unicode: str = ""

    artist: str = ""
    artist_unicode: str = ""

    creator: str = ""
    version: str = ""
    set_id: int = 0


@dataclass
class FileInfo:
    name: str
    offset: int
    size: int
    hash: tuple[bytes]
    created: datetime
    modified: datetime

    raw_data: bytes = b""

    _map_id: int = 0


# fmt: off
# FastRandom(1990)
known_plain = bytearray([
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


class XXTeaDecryptReader:
    def __init__(self, data, key: bytes) -> None:
        self.key: bytes = key
        self._data = memoryview(bytearray(data))
        self.offset: int = 0

    @property
    def data(self):
        return self._data[self.offset :]

    def __enter__(self):
        return self, self._data

    def __exit__(self, exc_type, exc_value, traceback):
        pass

    def read_bytes(self, size: int) -> tuple[bytes]:
        dec = xxtea_decrypt(self.data[:size], self.key)
        self.offset += size
        return struct.unpack(f"<{"B"*size}", dec)

    def read_byte(self) -> int:
        ret = struct.unpack("<b", xxtea_decrypt(self.data[:1], self.key))
        self.offset += 1
        return ret[0]

    def read_int32(self) -> int:
        ret = int.from_bytes(
            xxtea_decrypt(self.data[:4], self.key), "little", signed=True
        )
        self.offset += 4
        return ret

    def read_int64(self) -> int:
        ret = int.from_bytes(
            xxtea_decrypt(self.data[:8], self.key), "little", signed=True
        )
        self.offset += 8
        return ret

    def read_uleb128(self) -> int:
        result = shift = 0

        while True:
            b = int.from_bytes(xxtea_decrypt(self.data[0:1], self.key))
            self.offset += 1

            result |= (b & 0b01111111) << shift
            if (b & 0b10000000) == 0:
                break

            shift += 7

        return result

    def read_str(self) -> str:
        s_len = self.read_uleb128()
        ret = xxtea_decrypt(self.data[:s_len], self.key).decode()
        self.offset += s_len

        return ret


class BytesIOWrapper(io.BytesIO):
    def read(self, __size: int | None = None) -> bytes:
        return super().read(__size)

    def write(self, __buffer) -> int:
        return super().write(__buffer)

    def seek(self, __offset: int, __whence: int = 0) -> int:
        new_pos = super().seek(__offset, __whence)
        return new_pos

    def tell(self) -> int:
        cur_pos = super().tell()
        return cur_pos

    def write_uleb128(self, num: int):
        if num == 0:
            return b"\x00"

        ret = bytearray()
        length = 0

        while num > 0:
            ret.append(num & 0b01111111)
            num >>= 7
            if num != 0:
                ret[length] |= 0b10000000
            length += 1

        self.write(ret)

    def write_str(self, s: str):
        if s:
            encoded = s.encode()
            self.write_uleb128(len(encoded))
            self.write(encoded)
        else:
            self.write(b"\x00")


class OSZ2:
    def __init__(self) -> None:
        self.metadata: Metadata = Metadata()
        self.files: list[FileInfo] = []
        self.path: str = ""

        self._raw: bytes = b""

    def extract_osu_files(self) -> list[FileInfo]:
        files = []
        for file in self.files:
            if file._map_id:
                files.append(file)

        return files

    @classmethod
    def parse(cls, raw: bytes, file_type: int = 1) -> Union["OSZ2", None]:
        match file_type:
            case 1:
                return cls().parse_full_submit(raw)
            case 2:
                return cls().parse_patch(raw)
            case _:
                # TODO: maybe read the header and determine from there? or maybe that'd be useless
                services.logger.warn(
                    f"Someone tried to parse an invalid beatmap file type ({file_type})."
                )

        return

    # used for BSDIFF40 thingy
    def _offtin(self, data):
        x = struct.unpack("<Q", data)[0]

        if x & (1 << 63):
            x &= ~(1 << 63)
            x *= -1

        return x

    def parse_patch(self, raw: bytes) -> Union["OSZ2", None]:
        data = raw
        reader = Reader(data)

        # TODO patch parsing
        # the file should start with "BSDIFF40" otherwise it is NOT a patch file
        if reader.read_bytes(8) != (0x42, 0x53, 0x44, 0x49, 0x46, 0x46, 0x34, 0x30):
            services.logger.critical("A user tried to parse a non-patch file!")
            return

        # read length in BSDIFF40's header
        len_control = self._offtin(bytes(reader.read_bytes(8)))
        len_data = self._offtin(bytes(reader.read_bytes(8)))
        new_size = self._offtin(bytes(reader.read_bytes(8)))

        if len_control < 0 or len_data < 0 or new_size < 0:
            services.logger.critical(":WTF: (invalid patch file (sizes are corrupt))")
            return

        # decrypt starts here
        gz_control = gzip.GzipFile(
            fileobj=io.BytesIO(bytes(reader.read_bytes(len_control)))
        )
        gz_data = gzip.GzipFile(fileobj=io.BytesIO(bytes(reader.read_bytes(len_data))))
        gz_extra_data = gzip.GzipFile(
            fileobj=io.BytesIO(bytes(reader.data))
        )  # what the fuck?

        old_file_bytes = open(
            f".data/osz2/100000001.osz2", "rb"
        ).read()  # PLACEHOLDDDDDDDDEEEEEEEEEEEEEEEEEERRRR!!!!!!!!!!!!!!!!!
        new_file_bytes = bytearray(new_size)

        old_size = len(old_file_bytes)

        new_pos = 0
        old_pos = 0

        ctrl = [0, 0, 0]
        buffer = bytearray(8)

        # read control data
        while new_pos < new_size:
            for i in range(3):
                if gz_control.readinto(buffer) < 8:
                    services.logger.debug("corrupted patch (bad control)")
                    return
                ctrl[i] = self._offtin(buffer)

            if new_pos + ctrl[0] > new_size:
                services.logger.debug("corrupted patch (bad position)")
                return

            # read data (stuck here)
            for i in range(new_pos, new_pos + ctrl[0], 65536):
                if (
                    gz_data.readinto(memoryview(new_file_bytes[i : i + 65536]))
                    < ctrl[0]
                ):
                    services.logger.debug("corrupted patch (bad data)")
                    return

            # add old data to... new data?
            for i in range(ctrl[0]):
                if 0 <= old_pos + i < old_size:
                    new_file_bytes[new_pos + i] += old_file_bytes[old_pos + i]

            # adjust pointer
            new_pos += ctrl[0]
            old_pos += ctrl[0]

            if new_pos > new_size:
                services.logger.debug("corrupted patch (size too big???)")
                return

            # read extra stuff if there's any
            if (
                gz_extra_data.readinto(new_file_bytes[new_pos : new_pos + ctrl[1]])
                < ctrl[1]
            ):
                services.logger.debug("corrupted patch (bad extra data)")
                return

            # sanity check
            new_pos += ctrl[1]
            old_pos += ctrl[2]

        # not sure if these are needed but errrr...
        gz_control.close()
        gz_data.close()
        gz_extra_data.close()

        services.logger.info("OK!")

    def parse_full_submit(self, raw: bytes) -> Union["OSZ2", None]:
        data = raw
        reader = Reader(data)

        # the file should start with 0xEC, 0x48 and 0x4F otherwise it is NOT osz2
        if reader.read_bytes(3) != (0xEC, 0x48, 0x4F):
            services.logger.critical("A user tried to submit an invalid osz2 file")
            return

        # unused
        version = reader.read_byte()
        iv = bytearray(reader.read_bytes(16))

        hash_meta = reader.read_bytes(16)
        hash_file = reader.read_bytes(16)
        hash_data = reader.read_bytes(
            16
        )  # seems to be unused because IV was never used

        # metadata block
        # metadata_entries = reader.read_int32()
        metadata_entries_bytes = reader.read_bytes(4)  # i32
        metadata_entries = int.from_bytes(
            pack("4B", *metadata_entries_bytes), byteorder="little"
        )

        # save buffer for verification
        writer_meta_hash = BytesIOWrapper()
        writer_meta_hash.write(pack("4B", *metadata_entries_bytes))

        # read metadata
        for _ in range(metadata_entries):
            # type = reader.read_int16()
            type_bytes = reader.read_bytes(2)  # i16
            type = int.from_bytes(type_bytes, byteorder="little")
            value = reader.read_string(dot_net_str=True)

            match MetadataType(type):
                case MetadataType.Creator:
                    self.metadata.creator = value

                case MetadataType.Artist:
                    self.metadata.artist = value

                case MetadataType.ArtistUnicode:
                    self.metadata.artist_unicode = value

                case MetadataType.Title:
                    self.metadata.title = value

                case MetadataType.TitleUnicode:
                    self.metadata.title_unicode = value

                case MetadataType.Version:
                    self.metadata.version = value

                case MetadataType.BeatmapSetID:
                    self.metadata.set_id = int(value)

            # also save this to the buffer for verification
            writer_meta_hash.write(pack("2B", *type_bytes))
            writer_meta_hash.write_str(value)

        self.path = f".data/custom_beatmaps/{self.metadata.set_id} {self.metadata.artist} - {self.metadata.title}"

        # verify if hash is matched with what osz2 reported
        with writer_meta_hash.getbuffer() as meta_buffer:
            calculated_hash_meta = OSZ2.compute_osz_hash(
                meta_buffer, metadata_entries * 3, 0xA7
            )

            if calculated_hash_meta != pack("16B", *hash_meta):
                services.logger.critical(f"calculated: {calculated_hash_meta.hex()}")
                services.logger.critical(
                    f"osz2 report: {pack('16B', *hash_meta).hex()}"
                )
                services.logger.critical("bad hashes (hash_meta)")

                return

        # check how many .osu are there in the osz2
        num_files = reader.read_int32()

        # read all of them

        osu_file_and_map_id = []
        for i in range(num_files):
            file_name = reader.read_string(dot_net_str=True)
            map_id = reader.read_int32()

            osu_file_and_map_id.append((file_name, map_id))

        # prepare key and save key for later uses
        seed = f"{self.metadata.creator}yhxyfjo5{self.metadata.set_id}"
        KEY = hashlib.md5(seed.encode("ascii")).digest()

        # Verify this magic block using XTEA
        magic_key = xtea_decrypt(bytearray(reader.read_bytes(64)), KEY)
        if magic_key != known_plain:
            services.logger.critical(f"calculated: {known_plain.hex()}")
            services.logger.critical(f"osz2 report: {magic_key.hex()}")
            services.logger.critical("bad hashes (magic xtea block)")

            return

        # read encrypted data length and decrypt it
        length = reader.read_int32()
        for i in range(0, 16, 2):
            length -= hash_file[i] | (hash_file[i + 1] << 17)

        # read all .osu files in osz2 and set an offset
        file_info = reader.read_bytes(length)
        file_offset = reader.offset

        # prepare the buffer for XXTEA files verification and extraction
        with XXTeaDecryptReader(file_info, KEY) as (xxtea_reader, _):
            # verify if hash is matched with what osz2 reported
            file_info_count = xxtea_reader.read_int32()
            calculated_hash_file = OSZ2.compute_osz_hash(
                bytearray(file_info), file_info_count * 4, 0xD1
            )
            if calculated_hash_file != pack("16B", *hash_file):
                services.logger.critical(f"calculated: {calculated_hash_file.hex()}")
                services.logger.critical(
                    f"osz2 report: {pack('16B', *hash_file).hex()}"
                )
                services.logger.critical("bad hashes (hash_file)")
                return

            current_fileinfo_offset = xxtea_reader.read_int32()

            # intialize buffer and extract files info
            for i in range(file_info_count):
                # file name
                next_file_info_offset = 0
                file_name = xxtea_reader.read_str()
                file_hash = xxtea_reader.read_bytes(16)
                file_created = datetime_frombinary(xxtea_reader.read_int64())
                file_modified = datetime_frombinary(xxtea_reader.read_int64())
                current_fileinfo_offset = next_file_info_offset

                # prep new offset for files extraction
                if i + 1 < file_info_count:
                    next_file_info_offset = xxtea_reader.read_int32()
                else:
                    next_file_info_offset = len(data) - file_offset
                file_len = next_file_info_offset - current_fileinfo_offset

                file_info = FileInfo(
                    name=file_name,
                    hash=file_hash,
                    created=file_created,
                    modified=file_modified,
                    offset=current_fileinfo_offset,
                    size=file_len,
                )

                # TODO: add file info append here
                self.files.append(file_info)

        # data extraction
        for i in range(file_info_count):
            data_dec_len = xxtea_decrypt(bytearray(reader.read_bytes(4)), KEY)
            data_dec_len = (
                data_dec_len[0]
                | data_dec_len[1] << 8
                | data_dec_len[2] << 16
                | data_dec_len[3] << 24
            )

            decrypted_data = xxtea_decrypt(
                bytearray(reader.read_bytes(data_dec_len)), KEY
            )

            self.files[i].raw_data = decrypted_data

            for osu_map, map_id in osu_file_and_map_id:
                if osu_map != self.files[i].name:
                    continue

                self.files[i]._map_id = map_id

        # temporarily save stuff
        for file in self.files:
            path = f"{self.path}/{file.name}"
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb+") as beatmap:
                beatmap.write(file.raw_data)

        # make osz, after this, remove the osz2
        with zipfile.ZipFile(
            f".data/osz/{self.metadata.set_id} {self.metadata.artist} - {self.metadata.title}.osz",
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
        ) as osz:
            for file in self.files:
                osz.write(f"{self.path}/{file.name}", arcname=file.name)

        return self

    @staticmethod
    def compute_osz_hash(buffer: memoryview | bytearray, pos: int, swap: int) -> bytes:
        buffer[pos] ^= swap
        hash = bytearray(hashlib.md5(buffer).digest())
        buffer[pos] ^= swap

        for i in range(8):
            tmp = hash[i]
            hash[i] = hash[i + 8]
            hash[i + 8] = tmp

        hash[5] ^= 0x2D

        return bytes(hash)

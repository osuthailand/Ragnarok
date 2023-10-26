from base64 import b64decode

from dataclasses import dataclass
from enum import IntEnum, unique
import struct
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
# FastRandom(1990) but not sure if this is correct ones
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

# FastRandom(1990) but also not sure if this is correct ones
def generate_known_plain() -> bytearray:
    b = bytearray(64)

    y = 842502087
    x = 1990  # Seed for XTEA verification
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



class XXTeaDecryptReader:
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

    def read_uleb128(self) -> int:
        result = shift = 0

        while True:
            b = int.from_bytes(decrypt(self.data[0:1], self.key))
            self.offset += 1

            result |= (b & 0b01111111) << shift
            if (b & 0b10000000) == 0:
                break

            shift += 7

        return result
    
    def read_str(self) -> str:
        s_len = self.read_uleb128()
        ret = decrypt(self.data[:s_len], self.key).decode()
        self.offset += s_len

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

    def write_uleb128(self, num: int):
        if num == 0:
            return b'\x00'

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
            self.write(b'\x00')


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
            # check if it's a patch file instead (BSDIFF40)
            reader.offset = 0
            if reader.read_bytes(8) == (0x42, 0x53, 0x44, 0x49, 0x46, 0x46, 0x34, 0x30):
                log.fail("Patch file not supported yet!")
                return
            else:
                log.fail("User tried to submit an invalid osz2 file")
                return

        # unused
        version = reader.read_byte()
        iv = bytearray(reader.read_bytes(16))

        hash_meta = reader.read_bytes(16)
        hash_file = reader.read_bytes(16)
        hash_data = reader.read_bytes(16)

        # metadata block
        #metadata_entries = reader.read_int32()
        metadata_entries_bytes = reader.read_bytes(4)  # i32
        metadata_entries = int.from_bytes(pack('4B', *metadata_entries_bytes), byteorder='little')

        # save buffer for verification
        writerMetaHash = BytesIOWrapper()
        writerMetaHash.write(pack('4B', *metadata_entries_bytes))

        # read metadata
        metadata_info = []
        for _ in range(metadata_entries):
            # type = reader.read_int16()
            type_bytes = reader.read_bytes(2)  # i16
            type = int.from_bytes(type_bytes, byteorder='little')
            value = reader.read_str(dotNETString=True)

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

            # also save this to the buffer for verification
            writerMetaHash.write(pack('2B', *type_bytes))
            writerMetaHash.write_str(value)

        # verify if hash is matched with what osz2 reported
        with writerMetaHash.getbuffer() as meta_buffer:
            calculated_hash_meta = OSZ2.compute_osz_hash(meta_buffer, metadata_entries * 3, 0xa7)
            if calculated_hash_meta != pack('16B', *hash_meta):
                log.fail(f"calculated: {calculated_hash_meta.hex()}")
                log.fail(f"osz2 report: {pack('16B', *hash_meta).hex()}")
                log.fail("bad hashes (hash_meta)")
                return

        # check how many .osu are there in the osz2
        num_files = reader.read_int32()

        # read all of them
        # TODO: add them to dict for FileInfo
        for i in range(num_files):
            fileName = reader.read_str(dotNETString=True)
            map_id = reader.read_int32()

        # prepare key and save key for later uses
        seed = f"{c.metadata.creator}yhxyfjo5{c.metadata.set_id}"
        KEY = hashlib.md5(seed.encode("ascii")).digest()

        # TODO: Verify this magic block using XTEA
        magic_key = reader.read_bytes(64)  # skip for now

        # read encrypted data length and decrypt it
        length = reader.read_int32()
        for i in range(0, 16, 2):
            length -= hash_file[i] | (hash_file[i + 1] << 17)

        # read all .osu files in osz2 and set an offset
        file_info = reader.read_bytes(length)
        file_offset = reader.offset

        # prepare the buffer for XXTEA files verification and extraction
        with XXTeaDecryptReader(file_info, KEY) as (xxtea_reader, xxtea_block):
            # verify if hash is matched with what osz2 reported
            file_info_count = xxtea_reader.read_int32()
            calculated_hash_file = OSZ2.compute_osz_hash(bytearray(file_info), file_info_count * 4, 0xd1)
            if calculated_hash_file != pack('16B', *hash_file):
                 log.fail(f"calculated: {calculated_hash_file.hex()}")
                 log.fail(f"osz2 report: {pack('16B', *hash_file).hex()}")
                 log.fail("bad hashes (hash_file)")
                 return
            
            current_fileinfo_offset = xxtea_reader.read_int32()

            # intialize buffer and extract files info
            for i in range(file_info_count):
                # file name
                file_name = xxtea_reader.read_str()

                # file checksum
                file_hash = xxtea_reader.read_bytes(16)

                # file datetime created/modified
                # TODO: Make this readable by datetime
                file_date_created = xxtea_reader.read_int64()
                file_date_modified = xxtea_reader.read_int64()

                # prep new offset for files extraction
                next_file_info_offset = 0
                if (i + 1 < file_info_count):
                    next_file_info_offset = xxtea_reader.read_int32()
                else:
                    next_file_info_offset = len(data) - file_offset

                file_len = next_file_info_offset - current_fileinfo_offset
                # TODO: add file info append here
                current_fileinfo_offset = next_file_info_offset

        # data extraction
        # TODO: write full code when simon is here, for now have the first file only for now
        data_enc_len = reader.read_bytes(4)
        data_dec_len = decrypt(bytearray(data_enc_len), KEY)
        data_dec_len = (data_dec_len[0] |
                        data_dec_len[1] << 8 |
                        data_dec_len[2] << 16 |
                        data_dec_len[3] << 24)

        encrypted_data_tuple = reader.read_bytes(data_dec_len)
        encrypted_data = bytearray(encrypted_data_tuple)
        full_blocks = len(encrypted_data) // 64
        equivalent_value = full_blocks * 64
        leftover = len(encrypted_data) - equivalent_value

        with open(f".data/osz2/test_data/test_bytes", "wb+") as extract:
            decrypted_data = decrypt(encrypted_data[0:equivalent_value], KEY)
            decrypted_data += decrypt(encrypted_data[equivalent_value:equivalent_value+64], KEY)
            decrypted_data += decrypt(encrypted_data[equivalent_value+64:equivalent_value+64+leftover], KEY)
            extract.write(decrypted_data)
        
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

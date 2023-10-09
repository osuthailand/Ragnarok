import struct

from ctypes import c_uint32
from binascii import unhexlify
from math import ceil

class SimpleCryptor:
    def __init__(self, key):
        self._key = key

    def encrypt_bytes(self, buf, length):
        byte_key = bytes(self._key)
        prev_encrypted = 0

        for i in range(length):
            buf[i] = (buf[i] + (byte_key[i % 16] >> 2)) % 256
            buf[i] ^= self._rotate_left(byte_key[15 - i % 16], (prev_encrypted + length - i) % 7)
            buf[i] = self._rotate_right(buf[i], ~(prev_encrypted % 7))

            prev_encrypted = buf[i]

    def decrypt_bytes(self, buf, length):
        byte_key = bytes(self._key)
        prev_encrypted = 0

        for i in range(length):
            tmp_encrypted = buf[i]
            buf[i] = self._rotate_left(buf[i], ~(prev_encrypted % 7))
            buf[i] ^= self._rotate_left(byte_key[15 - i % 16], (prev_encrypted + length - i) % 7)
            buf[i] = (buf[i] - (byte_key[i % 16] >> 2)) % 256

            prev_encrypted = tmp_encrypted

    @staticmethod
    def _rotate_left(val, n):
        return ((val << n) | (val >> (8 - n))) & 0xFF

    @staticmethod
    def _rotate_right(val, n):
        return ((val >> n) | (val << (8 - n))) & 0xFF

class XTea:
    def __init__(self, key):
        self._key = key
        self._simple_cryptor = SimpleCryptor(key)

    def decrypt(self, buffer, start, count):
        self._encrypt_decrypt(buffer, start, count, encrypt=False)

    def _encrypt_decrypt(self, buffer, result, buffer_length, encrypt):
        full_word_count = buffer_length // 8
        leftover = buffer_length % 8

        int_word_ptr_b = struct.unpack(f"<{full_word_count * 2}I", buffer)
        int_word_ptr_o = [0] * (full_word_count * 2)
        int_word_ptr_b = int_word_ptr_b[-2:]

        if encrypt:
            for word_count in range(full_word_count):
                self._encrypt_word(int_word_ptr_b, int_word_ptr_o)
                int_word_ptr_b = int_word_ptr_b[2:]
        else:
            for word_count in range(full_word_count):
                self._decrypt_word(int_word_ptr_b, int_word_ptr_o)
                int_word_ptr_b = int_word_ptr_b[2:]

        if leftover == 0:
            return

        buffer_end = buffer[-leftover:]
        byte_word_ptr_b2 = buffer_end
        byte_word_ptr_o2 = result[:leftover]

        for _ in range(leftover):
            byte_word_ptr_b2 = byte_word_ptr_b2[1:]
            byte_word_ptr_o2 = byte_word_ptr_o2[1:]

        if encrypt:
            self._simple_cryptor.encrypt_bytes(buffer_result - left_over, left_over)
        else:
            self._simple_cryptor.decrypt_bytes(buffer_result - left_over, left_over)

    def bytes_to_vector(b: bytearray):
        return [int.from_bytes(b[:4], byteorder='big'), int.from_bytes(b[4:8], byteorder='big')]

    def decrypt_test(self, ciphertext: bytearray, key: bytearray):
        blocks = ceil(len(ciphertext) / 4.0)
        plaintext = ''
        for index in range(0, blocks, 2):
            # transform into vector
            v = self.bytes_to_vector(ciphertext[index*4:])
            p1, p2 = self._decrypt_word(v, key)
            plaintext += unhexlify(hex(p1)[2:]).decode()[::-1]
            plaintext += unhexlify(hex(p2)[2:]).decode()[::-1]
        return plaintext

    # this might be the most retarded thing that ive ever done ~Aoba
    def _encrypt_word(self, v, o):
        v0 = v[0]
        v1 = v[1]
        s = 0

        for _ in range(32):
            v0 += (((v1 << 4) ^ (v1 >> 5)) + v1) ^ (s + self._key[s & 3])
            s += 0x9E3779B9
            v1 += (((v0 << 4) ^ (v0 >> 5)) + v0) ^ (self._key[(s >> 11) & 3] + s)

        o[0] = v0
        o[1] = v1

    def _decrypt_word(v, key):
        v1, v0 = c_uint32(v[0]), c_uint32(v[1])
        s = c_uint32(0x9E3779B9 * 32)

        for _ in range(32):
            v1 -= (((v0 << 4) ^ (v0 >> 5)) + v0) ^ (self._key[(s >> 11) & 3] + s)
            s -= 0x9E3779B9
            v0 -= (((v1 << 4) ^ (v1 >> 5)) + v1) ^ (s + self._key[s & 3])
        
        return v0.value, v1.value
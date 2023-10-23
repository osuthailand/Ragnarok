# encoding: utf-8
from cffi import FFI
import sys
from os.path import join, dirname

from utils import log

__PATH = dirname(__file__)
__SOURCES = [join(__PATH, 'xxtea.c')]

ffi = FFI()
ffi.cdef('''
    void * xtea_encrypt_ecb(uint32_t* data, uint32_t block_count, uint32_t key[4]);
    void * xtea_decrypt_ecb(uint32_t* data, uint32_t block_count, uint32_t key[4]);
    void * xtea_encrypt_cbc(uint32_t* data, uint32_t block_count, uint32_t key[4], uint32_t iv[2]);
    void * xtea_decrypt_cbc(uint32_t* data, uint32_t block_count, uint32_t key[4], uint32_t iv[2]);
    void * xtea_encrypt_cfb(uint32_t* data, uint32_t block_count, uint32_t key[4], uint32_t iv[2]);
    void * xtea_decrypt_cfb(uint32_t* data, uint32_t block_count, uint32_t key[4], uint32_t iv[2]);
    void * xtea_encrypt_ctr(uint32_t* data, uint32_t block_count, uint32_t key[4], uint32_t nonce[2]);
    void * xtea_decrypt_ctr(uint32_t* data, uint32_t block_count, uint32_t key[4], uint32_t nonce[2]);
    void * xtea_encrypt_ofb(uint32_t* data, uint32_t block_count, uint32_t key[4], uint32_t iv[2]);
    void * xtea_decrypt_ofb(uint32_t* data, uint32_t block_count, uint32_t key[4], uint32_t iv[2]);
    void * xtea_encrypt_pcbc(uint32_t* data, uint32_t block_count, uint32_t key[4], uint32_t iv[2]);
    void * xtea_decrypt_pcbc(uint32_t* data, uint32_t block_count, uint32_t key[4], uint32_t iv[2]);
    void free(void * ptr);
''')
lib = ffi.verify('#include <xtea.h>', sources = __SOURCES, include_dirs=[__PATH])

if sys.version_info < (3, 0):
    def __tobytes(v):
        if isinstance(v, unicode):
            return v.encode('utf-8')
        else:
            return v
else:
    def __tobytes(v):
        if isinstance(v, str):
            return v.encode('utf-8')
        else:
            return v

def xtea_enc(data, key):
    '''encrypt the data with the key'''
    data = __tobytes(data)
    data_len = len(data)
    data = ffi.from_buffer(data)
    key = ffi.from_buffer(__tobytes(key))
    out_len = ffi.new('size_t *')
    result = lib.xtea_encrypt_ecb(data, data_len, key, out_len)
    ret = ffi.buffer(result, out_len[0])[:]
    lib.free(result)
    return ret

def xtea_dec(data, key):
    '''decrypt the data with the key'''
    data_len = len(data)
    data = ffi.from_buffer(data)
    key = ffi.from_buffer(__tobytes(key))
    out_len = ffi.new('size_t *')
    result = lib.xtea_decrypt_ecb(data, data_len, key, out_len)
    ret = ffi.buffer(result, out_len[0])[:]
    lib.free(result)
    return ret
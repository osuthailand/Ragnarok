# encoding: utf-8
from cffi import FFI
from os.path import join, dirname

from utils import log

__PATH = dirname(__file__)
__SOURCES = [join(__PATH, 'xxtea.c')]

ffi = FFI()

#prepare struct
ffi.cdef('''
    #define MAX 16

    struct XXTea {
        uint8_t _key[MAX];
        uint32_t _n;
    };
         
    void XXTea_Init(struct XXTea* tea, const uint8_t* key);
    void XXTea_EncryptDecryptXXTea(struct XXTea* tea, char* buffer, int bufferLength, int encrypt);
    void XXTea_EncryptWords(uint32_t* v, uint8_t* key, uint32_t n);
    void XXTea_DecryptWords(uint32_t* v, uint8_t* key, uint32_t n);
    void free(void * ptr);
''')
lib = ffi.verify('#include <xxtea.h>', sources = __SOURCES, include_dirs=[__PATH])

def decrypt(data, key):
    data_len = len(data)
    log.debug(f'{data_len=}')
    log.debug(f'{data=}') # 182 bytes of encrypted crap
    data = ffi.from_buffer(data)
    key_len = len(key)
    log.debug(f'{key_len=}')
    log.debug(f'{key=}') # '\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f'
    key_uint8 = ffi.new("uint8_t[16]", key)
    out_len = ffi.new('size_t *')

    log.debug(f'{out_len=}')
    
    # prep struct
    tea = ffi.new("struct XXTea *")
    tea._key = key_uint8
    tea._n = ffi.cast("uint32_t *", 16)
    log.debug(tea)
    log.debug(tea._key)
    log.debug(tea._n)
    lib.XXTea_Init(tea, key_uint8)
    
    result = lib.XXTea_EncryptDecryptXXTea(tea, data, data_len, 0)
    log.debug("AIIIEEEE")
    log.debug(result)
    ret = ffi.buffer(result, out_len[0])[:]
    lib.free(result)
    return ret
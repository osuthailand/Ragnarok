# encoding: utf-8
from cffi import FFI
from os.path import join, dirname

__PATH = dirname(__file__)
__SOURCES = [join(__PATH, 'xxtea.c')]

ffi = FFI()

# prepare struct
ffi.cdef('''
    void XTea_Decrypt(const uint32_t* key, const void* src, void* dst, int size);

    void XXTea_Decrypt(const uint32_t* key, const void* src, void* dst, int size);
    void XXTea_Encrypt(const uint32_t* key, const void* src, void* dst, int size);
''')
lib = ffi.verify('#include <xxtea.h>', sources=__SOURCES,
                 include_dirs=[__PATH], extra_compile_args=['-Wno-unused'])


def xtea_decrypt(data: bytes, key: bytes):
    data_len = len(data)

    # make a copy of the data and key buffers
    data_cbuf = ffi.from_buffer(data)
    key_cbuf = ffi.from_buffer(key)

    # cast them to the appropriate types
    data_casted = ffi.cast("char *", data_cbuf)
    key_casted = ffi.cast("uint32_t *", key_cbuf)

    # call the code
    lib.XTea_Decrypt(key_casted, data_casted, data_casted, data_len)

    # copy
    return ffi.buffer(data_cbuf, data_len)[:]


def xxtea_decrypt(data: bytes, key: bytes):
    data_len = len(data)

    # make a copy of the data and key buffers
    data_cbuf = ffi.from_buffer(data)
    key_cbuf = ffi.from_buffer(key)

    # cast them to the appropriate types
    data_casted = ffi.cast("char *", data_cbuf)
    key_casted = ffi.cast("uint32_t *", key_cbuf)

    # call the code
    lib.XXTea_Decrypt(key_casted, data_casted, data_casted, data_len)

    # copy
    return ffi.buffer(data_cbuf, data_len)[:]

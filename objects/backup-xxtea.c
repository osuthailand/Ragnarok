/**********************************************************\
|                                                          |
| xxtea.c                                                  |
|                                                          |
| XXTEA encryption algorithm library for C.                |
| Modded to work with osu! FastStreamProvider              |
|                                                          |
| Encryption Algorithm Authors:                            |
|      David J. Wheeler                                    |
|      Roger M. Needham                                    |
|                                                          |
| Code Authors: Chen fei <cf850118@163.com>                |
|               Ma Bingyao <mabingyao@gmail.com>           |
|               Suzukaze Aoba <aoba@rina.place>            |
|               Simon G. <simon@rina.place>                |
| LastModified: Oct 22, 2023                               |
|                                                          |
\**********************************************************/

#include "xxtea.h"

#include <string.h>
#include <stdio.h>
#if defined(_MSC_VER) && _MSC_VER < 1600
typedef unsigned __int8 uint8_t;
typedef unsigned __int32 uint32_t;
#else
#if defined(__FreeBSD__) && __FreeBSD__ < 5
/* FreeBSD 4 doesn't have stdint.h file */
#include <inttypes.h>
#else
#include <stdint.h>
#endif
#endif

#include <sys/types.h> /* This will likely define BYTE_ORDER */

#ifndef BYTE_ORDER
#if (BSD >= 199103)
#include <machine/endian.h>
#else
#if defined(linux) || defined(__linux__)
#include <endian.h>
#else
#define LITTLE_ENDIAN 1234 /* least-significant byte first (vax, pc) */
#define BIG_ENDIAN 4321    /* most-significant byte first (IBM, net) */
#define PDP_ENDIAN 3412    /* LSB first in word, MSW first in long (pdp)*/

#if defined(__i386__) || defined(__x86_64__) || defined(__amd64__) ||    \
    defined(vax) || defined(ns32000) || defined(sun386) ||               \
    defined(MIPSEL) || defined(_MIPSEL) || defined(BIT_ZERO_ON_RIGHT) || \
    defined(__alpha__) || defined(__alpha)
#define BYTE_ORDER LITTLE_ENDIAN
#endif

#if defined(sel) || defined(pyr) || defined(mc68000) || defined(sparc) ||      \
    defined(is68k) || defined(tahoe) || defined(ibm032) || defined(ibm370) ||  \
    defined(MIPSEB) || defined(_MIPSEB) || defined(_IBMR2) || defined(DGUX) || \
    defined(apollo) || defined(__convex__) || defined(_CRAY) ||                \
    defined(__hppa) || defined(__hp9000) ||                                    \
    defined(__hp9000s300) || defined(__hp9000s700) ||                          \
    defined(BIT_ZERO_ON_LEFT) || defined(m68k) || defined(__sparc)
#define BYTE_ORDER BIG_ENDIAN
#endif
#endif /* linux */
#endif /* BSD */
#endif /* BYTE_ORDER */

#ifndef BYTE_ORDER
#ifdef __BYTE_ORDER
#if defined(__LITTLE_ENDIAN) && defined(__BIG_ENDIAN)
#ifndef LITTLE_ENDIAN
#define LITTLE_ENDIAN __LITTLE_ENDIAN
#endif
#ifndef BIG_ENDIAN
#define BIG_ENDIAN __BIG_ENDIAN
#endif
#if (__BYTE_ORDER == __LITTLE_ENDIAN)
#define BYTE_ORDER LITTLE_ENDIAN
#else
#define BYTE_ORDER BIG_ENDIAN
#endif
#endif
#endif
#endif

// Constant
#define MX (((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4))) ^ ((sum ^ y) + (key[(p & 3) ^ e] ^ z))
#define MAX 16
#define MAX_BYTES 64
#define DELTA 0x9e3779b9

#define FIXED_KEY                                     \
    size_t i;                                         \
    uint8_t fixed_key[16];                            \
    memcpy(fixed_key, key, 16);                       \
    for (i = 0; (i < 16) && (fixed_key[i] != 0); ++i) \
        ;                                             \
    for (++i; i < 16; ++i)                            \
        fixed_key[i] = 0;

#define rotateLeft(val, n) ((uint8_t)((val << n) | (val >> (8 - n))))
#define rotateRight(val, n) ((uint8_t)((val >> n) | (val << (8 - n))))

static uint32_t *xxtea_to_uint_array(const uint8_t *data, size_t len, int inc_len, size_t *out_len)
{
    uint32_t *out;
#if !(defined(BYTE_ORDER) && (BYTE_ORDER == LITTLE_ENDIAN))
    size_t i;
#endif
    size_t n;

    // n = (((len & 3) == 0) ? (len >> 2) : ((len >> 2) + 1));
    n = len;
    if (inc_len)
    {
        out = (uint32_t *)calloc(n + 1, sizeof(uint32_t));
        if (!out)
            return NULL;
        out[n] = (uint32_t)len;
        *out_len = n + 1;
    }
    else
    {
        out = (uint32_t *)calloc(n, sizeof(uint32_t));
        if (!out)
            return NULL;
        *out_len = n;
    }
#if defined(BYTE_ORDER) && (BYTE_ORDER == LITTLE_ENDIAN)
    memcpy(out, data, len);
#else
    for (i = 0; i < len; ++i)
    {
        out[i >> 2] |= (uint32_t)data[i] << ((i & 3) << 3);
    }
#endif

    return out;
}

static uint8_t * xxtea_to_ubyte_array(const uint32_t * data, size_t len, int inc_len, size_t * out_len) {
    uint8_t *out;
#if !(defined(BYTE_ORDER) && (BYTE_ORDER == LITTLE_ENDIAN))
    size_t i;
#endif
    size_t m, n;

    n = len << 2;

    if (inc_len) {
        m = data[len - 1];
        n -= 4;
        if ((m < n - 3) || (m > n)) return NULL;
        n = m;
    }

    out = (uint8_t *)malloc(n + 1);

#if defined(BYTE_ORDER) && (BYTE_ORDER == LITTLE_ENDIAN)
    memcpy(out, data, n);
#else
    for (i = 0; i < n; ++i) {
        out[i] = (uint8_t)(data[i >> 2] >> ((i & 3) << 3));
    }
#endif

    out[n] = '\0';
    *out_len = n;

    return out;
}

// static uint8_t *xxtea_to_ubyte_array(const uint32_t *data, size_t len, int inc_len, size_t *out_len)
// {
//     uint8_t *out;
// #if !(defined(BYTE_ORDER) && (BYTE_ORDER == LITTLE_ENDIAN))
//     size_t i;
// #endif
//     size_t m, n;

//     n = len;

//     if (inc_len)
//     {
//         m = data[len - 1];
//         n -= 4;
//         if ((m < n - 3) || (m > n))
//             return NULL;
//         n = m;
//     }

//     out = (uint8_t *)malloc(n + 1);

// #if defined(BYTE_ORDER) && (BYTE_ORDER == LITTLE_ENDIAN)
//     memcpy(out, data, n);
// #else
//     for (i = 0; i < n; ++i)
//     {
//         out[i] = (uint8_t)(data[i >> 2] >> ((i & 3) << 3));
//     }
// #endif

//     out[n] = '\0';
//     *out_len = n;

//     return out;
// }

// TODO: add peppy's modded encrypt
//       https://github.com/ppy/osu-stream/blob/0a2ceac47e789c42a1e91478661ef4528f327d94/osu!stream/Helpers/osu!common/FastEncryptionProvider.cs#L457
static uint32_t *xxtea_uint_encrypt(uint32_t *data, size_t len, uint32_t *key)
{
    uint32_t n = (uint32_t)len - 1;
    uint32_t z = data[n], y, p, q = 6 + 52 / (n + 1), sum = 0, e;

    if (n < 1)
        return data;

    while (0 < q--)
    {
        sum += DELTA;
        e = sum >> 2 & 3;

        for (p = 0; p < n; p++)
        {
            y = data[p + 1];
            z = data[p] += MX;
        }

        y = data[0];
        z = data[n] += MX;
    }

    return data;
}

static uint32_t * xxtea_uint_decrypt(uint32_t * data, size_t len, uint32_t * key) {
    uint32_t n = (uint32_t)len - 1;
    uint32_t z, y = data[0], p, q = 6 + 52 / (n + 1), sum = q * DELTA, e;

    if (n < 1) return data;

    while (sum != 0) {
        e = sum >> 2 & 3;

        for (p = n; p > 0; p--) {
            z = data[p - 1];
            y = data[p] -= MX;
        }

        z = data[n];
        y = data[0] -= MX;
        sum -= DELTA;
    }

    return data;
}

// TODO: add peppy's modded decrypt
//       https://github.com/ppy/osu-stream/blob/0a2ceac47e789c42a1e91478661ef4528f327d94/osu!stream/Helpers/osu!common/FastEncryptionProvider.cs#L479
static uint32_t *decrypt_word(uint32_t *v, uint32_t * key)
{
    uint32_t n = MAX;

    uint32_t z, y = v[0], q = 6 + 52 / n, sum = q * DELTA;
    uint32_t p, e;

    //if (n < 1) return v;

    do {
        e = (sum >> 2) & 3;
        
        for (p = n - 1; p > 0; p--) {
            z = v[p - 1];
            y = v[p] -= MX;
        }

        z = v[n - 1];
        y = v[0] -= MX;
    } while ((sum -= DELTA) != 0);

    return v;
}

static uint32_t *xxtea_uint_decrypt_n_defined(uint32_t *data, size_t len, uint32_t *key, uint32_t n)
{
    uint32_t z, p, e; 
    uint32_t y = data[0];
    uint32_t q = 6 + 52 / n;
    uint32_t sum = q * DELTA;

    while ((sum -= DELTA) != 0)
    {
        e = (sum >> 2) & 3;

        for (p = n - 1; p > 0; p--)
        {
            z = data[p - 1];
            y = data[p] -= MX;
        }

        z = data[n - 1];
        y = data[0] -= MX;

    }

    return data;
}

static uint8_t *xxtea_ubyte_encrypt(const uint8_t *data, size_t len, const uint8_t *key, size_t *out_len)
{
    uint8_t *out;
    uint32_t *data_array, *key_array;
    size_t data_len, key_len;

    if (!len)
        return NULL;

    data_array = xxtea_to_uint_array(data, len, 1, &data_len);
    if (!data_array)
        return NULL;

    key_array = xxtea_to_uint_array(key, 16, 0, &key_len);
    if (!key_array)
    {
        free(data_array);
        return NULL;
    }

    out = xxtea_to_ubyte_array(xxtea_uint_encrypt(data_array, data_len, key_array), data_len, 0, out_len);

    free(data_array);
    free(key_array);

    return out;
}

static uint8_t *xxtea_ubyte_decrypt(const uint8_t *data, size_t len, const uint8_t *key, size_t *out_len)
{
    uint8_t *out;
    uint32_t *data_array, *key_array;
    size_t data_len, key_len;

    if (!len)
        return NULL;

    data_array = xxtea_to_uint_array(data, len, 0, &data_len);
    if (!data_array)
        return NULL;

    key_array = xxtea_to_uint_array(key, 16, 0, &key_len);
    if (!key_array)
    {
        free(data_array);
        return NULL;
    }

    out = xxtea_to_ubyte_array(xxtea_uint_decrypt(data_array, data_len, key_array), data_len, 1, out_len);

    free(data_array);
    free(key_array);

    return out;
}

static uint8_t *xxtea_ubyte_decrypt_modified(uint8_t *data, size_t len, const uint8_t *key, size_t *out_len)
{
    uint32_t* dd;
    uint32_t* dd2;
    size_t data_len, key_len;
    uint32_t* data_array = xxtea_to_uint_array(data, len, 0, &data_len);
    if (!data_array)
        return NULL;

    uint32_t* key_array = xxtea_to_uint_array(key, 16, 0, &key_len);
    if (!key_array)
    {
        free(data_array);
        return NULL;
    }
    uint32_t full_word_count = (uint32_t)len / (4 * 16); // n max bytes
    uint32_t leftover = (uint32_t)len % (4 * 16);
    uint32_t n = 16;

    for (uint32_t word_count = 0; word_count < full_word_count; word_count++)
    {
        dd = xxtea_uint_decrypt_n_defined(data_array, len,key_array, n);
        dd += 4;

    }

    if (leftover == 0)
    {
        return NULL;
    }

    n = leftover / 4;
    if (n > 1)
    {
        dd2 = xxtea_uint_decrypt_n_defined(data_array, len, key_array, n);
        dd += 4;

        leftover -= n * 4;
        if (leftover == 0)
        {
            return NULL;
        }
    }

    uint8_t* out = xxtea_to_ubyte_array(*dd + *dd2, data_len, 1, out_len);
    //out = xxtea_to_ubyte_array(xxtea_uint_encrypt(data_array, data_len, key_array), data_len, 0, out_len);

    // uint8_t* byteWordPtr = (uint8_t*)data;
    // byteWordPtr += len - leftover;
    // simpleDecryptBytes(byteWordPtr, (int32_t)leftover, key);

    free(data_array);
    free(key_array);

    return out;
}

static uint8_t *decryptXXTea(const uint8_t *bufferPtr, size_t bufferLength, uint8_t * key) {
    uint8_t *out;
    uint32_t *data_decoded, *key_array;

    uint32_t fullWordCount = (uint32_t)bufferLength / MAX_BYTES; // Data Length
    uint32_t leftOver = (uint32_t)bufferLength % MAX_BYTES; // also data length

    uint32_t* uBufferPtr = (uint32_t*)bufferPtr; // whatever the fuck this is

    uint32_t n = MAX;

    uint32_t rounds = 6 + 52 / n;

    size_t buff_len, key_len;

    if (!bufferLength)
        return NULL;

    for (uint32_t wordCount = 0; wordCount < fullWordCount; wordCount++) {
        uint32_t y, z, sum;
        uint32_t p, e;
        sum = rounds * DELTA;

        y = uBufferPtr[0];
        do {
            e = (sum >> 2) & 3;
            for (p = MAX - 1; p > 0; p--) {
                z = uBufferPtr[p - 1];
                y = uBufferPtr[p] -= MX;
            }

            z = uBufferPtr[MAX - 1];
            y = uBufferPtr[0] -= MX;
        } while ((sum -= DELTA) != 0);

        uBufferPtr += MAX;
    }

    if (leftOver == 0)
        return;

    n = leftOver / 4;
    if (n > 1) {
        data_decoded = decrypt_word(uBufferPtr, key);
        if (!data_decoded)
            return NULL;

        key_array = xxtea_to_uint_array(key, 16, 0, &key_len);
        if (!key_array)
        {
            free(data_decoded);
            return NULL;
        }

        leftOver -= n * 4;
        if (leftOver == 0)
            return;
    }

    uint8_t* resultBuffer = bufferPtr;
    resultBuffer += bufferLength - leftOver;

    out = simpleDecryptBytes(resultBuffer, (int)leftOver, key);

    free(data_decoded);
    free(key_array);

    return out;
}

void simpleEncryptBytes(uint8_t *buf, size_t length, const uint8_t *key)
{
    uint8_t *keyB = (uint8_t *)key;
    uint8_t prevE = 0; // previous encrypted
    for (size_t i = 0; i < length; i++)
    {
        buf[i] = (uint8_t)((buf[i] + (keyB[i % 16] >> 2)) % 256);
        buf[i] ^= rotateLeft(keyB[15 - i % 16], (uint8_t)((prevE + length - i) % 7));
        buf[i] = rotateRight(buf[i], (uint8_t)((~(uint32_t)(prevE)) % 7));

        prevE = buf[i];
    }
}

void simpleDecryptBytes(uint8_t *buf, size_t length, const uint8_t *key)
{
    uint8_t *keyB = (uint8_t *)key;
    uint8_t prevE = 0; // previous encrypted
    for (size_t i = 0; i < length; i++)
    {
        uint8_t tmpE = buf[i];
        buf[i] = rotateLeft(buf[i], (uint8_t)((~(uint32_t)(prevE)) % 7));
        buf[i] ^= rotateLeft(keyB[15 - i % 16], (uint8_t)((prevE + length - i) % 7));
        buf[i] = (uint8_t)((buf[i] - (keyB[i % 16] >> 2)) % 256);

        prevE = tmpE;
    }
}

// public functions

void *xxtea_encrypt(const void *data, size_t len, const void *key, size_t *out_len)
{
    FIXED_KEY
    return xxtea_ubyte_encrypt((const uint8_t *)data, len, fixed_key, out_len);
}

void *xxtea_decrypt(const void *data, size_t len, const void *key, size_t *out_len)
{
    FIXED_KEY
    return xxtea_ubyte_decrypt((const uint8_t *)data, len, fixed_key, out_len);
}

void *xxtea_encrypt_bkey(const void *data, size_t len, const void *key, size_t key_len, size_t *out_len)
{
    if (key_len % 8)
        return NULL;

    return xxtea_ubyte_encrypt((const uint8_t *)data, len, key, out_len);
}

void *xxtea_decrypt_bkey(const void *data, size_t len, const void *key, size_t key_len, size_t *out_len)
{
    if (key_len % 8)
        return NULL;

    printf("You're using xxtea_decrypt_bkey\n");
    printf("%s\n", key);

    return xxtea_ubyte_decrypt((const uint8_t *)data, len, key, out_len);
}

void *simon_xxtea_decrypt_bkey(const void *data, size_t len, const void *key, size_t key_len, size_t *out_len)
{
    if (key_len % 8)
        return NULL;

    return xxtea_ubyte_decrypt_modified((uint8_t *)data, len, key, out_len);
}

void *aoba_xxtea_decrypt_bkey(const void *data, size_t len, const void *key)
{
    return decryptXXTea((uint8_t *)data, len, key);
}
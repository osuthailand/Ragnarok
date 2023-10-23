/**********************************************************\
|                                                          |
| xxtea.h                                                  |
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

#ifndef XXTEA_INCLUDED
#define XXTEA_INCLUDED

#include <stdlib.h>

#ifdef __cplusplus
extern "C" {
#endif

//test
void *aoba_xxtea_decrypt_bkey(const void *data, size_t len, const void *key);

/**
 * Function: xxtea_encrypt
 * @data:    Data to be encrypted
 * @len:     Length of the data to be encrypted
 * @key:     Symmetric key
 * @out_len: Pointer to output length variable
 * Returns:  Encrypted data or %NULL on failure
 *
 * Caller is responsible for freeing the returned buffer.
 */
void * xxtea_encrypt(const void * data, size_t len, const void * key, size_t * out_len);

void * xxtea_encrypt_bkey(const void * data, size_t len, const void * key, size_t key_len, size_t * out_len);

/**
 * Function: xxtea_decrypt
 * @data:    Data to be decrypted
 * @len:     Length of the data to be decrypted
 * @key:     Symmetric key
 * @out_len: Pointer to output length variable
 * Returns:  Decrypted data or %NULL on failure
 *
 * Caller is responsible for freeing the returned buffer.
 */
void * xxtea_decrypt(const void * data, size_t len, const void * key, size_t * out_len);

void * xxtea_decrypt_bkey(const void * data, size_t len, const void * key, size_t key_len, size_t * out_len);

void * simon_xxtea_decrypt_bkey(const void * data, size_t len, const void * key, size_t key_len, size_t * out_len);

#ifdef __cplusplus
}
#endif

#endif
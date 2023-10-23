/**********************************************************\
|                                                          |
| xtea.h                                                   |
|                                                          |
| XTEA encryption algorithm library for C.                 |
|                                                          |
| Encryption Algorithm Authors:                            |
|      David J. Wheeler                                    |
|      Roger M. Needham                                    |
|                                                          |
| Code Author: Suzukaze Aoba <aoba@rina.place>             |
|                                                          |
| LastModified: Oct 22, 2023                               |
|                                                          |
\**********************************************************/

#ifndef __XTEA_H__
#define __XTEA_H__

#ifdef __cplusplus
extern "C" {
#endif

/** Electronic Code Book mode **/
void * xtea_encrypt_ecb(uint32_t* data, uint32_t block_count, uint32_t key[4]);
void * xtea_decrypt_ecb(uint32_t* data, uint32_t block_count, uint32_t key[4]);

/** Cipher Block Chaining mode **/
void * xtea_encrypt_cbc(uint32_t* data, uint32_t block_count, uint32_t key[4], uint32_t iv[2]);
void * xtea_decrypt_cbc(uint32_t* data, uint32_t block_count, uint32_t key[4], uint32_t iv[2]);

/** Cipher Feedback mode **/
void * xtea_encrypt_cfb(uint32_t* data, uint32_t block_count, uint32_t key[4], uint32_t iv[2]);
void * xtea_decrypt_cfb(uint32_t* data, uint32_t block_count, uint32_t key[4], uint32_t iv[2]);

/** Counter mode **/
void * xtea_encrypt_ctr(uint32_t* data, uint32_t block_count, uint32_t key[4], uint32_t nonce[2]);
void * xtea_decrypt_ctr(uint32_t* data, uint32_t block_count, uint32_t key[4], uint32_t nonce[2]);

/** Output Feedback mode **/
void * xtea_encrypt_ofb(uint32_t* data, uint32_t block_count, uint32_t key[4], uint32_t iv[2]);
void * xtea_decrypt_ofb(uint32_t* data, uint32_t block_count, uint32_t key[4], uint32_t iv[2]);

/** Propagating Cipher Block Chaining mode **/
void * xtea_encrypt_pcbc(uint32_t* data, uint32_t block_count, uint32_t key[4], uint32_t iv[2]);
void * xtea_decrypt_pcbc(uint32_t* data, uint32_t block_count, uint32_t key[4], uint32_t iv[2]);


#ifdef __cplusplus
};
#endif

#endif /* __XTEA_H__ */
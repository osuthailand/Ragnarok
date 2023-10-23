/**********************************************************\
|                                                          |
| xtea.c                                                   |
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

#include "xtea.h"

#include <stdint.h>

void xtea_encrypt(uint32_t val[2], uint32_t key[4])
{
    uint32_t v0 = val[0], v1 = val[1];
    uint32_t k0 = key[0], k1 = key[1], k2 = key[2], k3 = key[3];
    uint32_t delta = 0x9E3779B9, sum = 0, i;

    for (i =  0; i < 32; i++)
    {

        v0  += (((v1 << 4) ^ (v1 >> 5)) + v1) ^ (sum + key[sum & 3]);
        sum += delta;
        v1  += (((v0 << 4) ^ (v0 >> 5)) + v0) ^ (sum + key[(sum>>11) & 3]);
    }

    val[0] = v0;
    val[1] = v1;
}

void xtea_decrypt(uint32_t val[2], uint32_t key[4])
{
    uint32_t v0 = val[0], v1 = val[1];
    uint32_t k0 = key[0], k1 = key[1], k2 = key[2], k3 = key[3];
    uint32_t delta = 0x9E3779B9, sum = 0xC6EF3720, i;

    for (i =  0; i < 32; i++)
    {

        v1  -= (((v0 << 4) ^ (v0 >> 5)) + v0) ^ (sum + key[(sum>>11) & 3]);
        sum -= delta;
        v0  -= (((v1 << 4) ^ (v1 >> 5)) + v1) ^ (sum + key[sum & 3]);
    }

    val[0] = v0;
    val[1] = v1;
}

void 
xtea_encrypt_ecb(uint32_t* data, uint32_t block_count, uint32_t key[4])
{
    uint32_t i;

    for (i = 0; i < block_count; i += 2)
        xtea_encrypt(&data[i], key);
}

void 
xtea_decrypt_ecb(uint32_t* data, uint32_t block_count, uint32_t key[4])
{
    uint32_t i;

    for (i = 0; i < block_count; i += 2)
        xtea_decrypt(&data[i], key);
}

void 
xtea_encrypt_cbc(uint32_t* data, uint32_t block_count, uint32_t key[4], uint32_t iv[2])
{
    uint32_t i;
    uint32_t prev_block[2];

    prev_block[0] = iv[0];
    prev_block[1] = iv[1];

    for (i = 0; i < block_count; i += 2)
    {

        data[i    ] ^= prev_block[0];
        data[i + 1] ^= prev_block[1];

        xtea_encrypt(&data[i], key);

        prev_block[0] = data[i    ];
        prev_block[1] = data[i + 1];

    }
}

void 
xtea_decrypt_cbc(uint32_t* data, uint32_t block_count, uint32_t key[4], uint32_t iv[2])
{
    uint32_t i;
    uint32_t prev_block[2];
    uint32_t cipher_block[2];

    prev_block[0] = iv[0];
    prev_block[1] = iv[1];

    for (i = 0; i < block_count; i += 2)
    {
        cipher_block[0] = data[i    ];
        cipher_block[1] = data[i + 1];

        xtea_decrypt(&data[i], key);

        data[i    ] ^= prev_block[0];
        data[i + 1] ^= prev_block[1];

        prev_block[0] = cipher_block[0];
        prev_block[1] = cipher_block[1];
    }
}

void 
xtea_encrypt_cfb(uint32_t* data, uint32_t block_count, uint32_t key[4], uint32_t iv[2])
{
    uint32_t i;
    uint32_t prev_block[2];

    prev_block[0] = iv[0];
    prev_block[1] = iv[1];

    for (i = 0; i < block_count; i += 2)
    {
        xtea_encrypt(prev_block, key);

        data[i    ] ^= prev_block[0];
        data[i + 1] ^= prev_block[1];

        prev_block[0] = data[i    ];
        prev_block[1] = data[i + 1];
    }
}

void 
xtea_decrypt_cfb(uint32_t* data, uint32_t block_count, uint32_t key[4], uint32_t iv[2])
{
    uint32_t i;
    uint32_t prev_block[2];
    uint32_t cipher_block[2];

    prev_block[0] = iv[0];
    prev_block[1] = iv[1];

    for (i = 0; i < block_count; i += 2)
    {

        cipher_block[0] = data[i    ];
        cipher_block[1] = data[i + 1];

        xtea_encrypt(prev_block, key);

        data[i    ] ^= prev_block[0];
        data[i + 1] ^= prev_block[1];

        prev_block[0] = cipher_block[0];
        prev_block[1] = cipher_block[1];
    }
}

void 
xtea_encrypt_ctr(uint32_t* data, uint32_t block_count, uint32_t key[4], uint32_t nonce[2])
{
    uint32_t i;
    uint32_t nonce_local[2];

    nonce_local[0] = nonce[0];
    nonce_local[1] = nonce[1];

    for (i = 0; i < block_count; i += 2)
    {

        xtea_encrypt(nonce_local, key);

        data[i    ] ^= nonce_local[0];
        data[i + 1] ^= nonce_local[1];

        nonce_local[1] ++;
    }
}

void 
xtea_decrypt_ctr(uint32_t* data, uint32_t block_count, uint32_t key[4], uint32_t nonce[2])
{
    uint32_t i;
    uint32_t nonce_local[2];

    nonce_local[0] = nonce[0];
    nonce_local[1] = nonce[1];

    for (i = 0; i < block_count; i += 2)
    {

        xtea_encrypt(nonce_local, key);

        data[i    ] ^= nonce_local[0];
        data[i + 1] ^= nonce_local[1];

        nonce_local[1] ++;
    }
}

void 
xtea_encrypt_ofb(uint32_t* data, uint32_t block_count, uint32_t key[4], uint32_t iv[2])
{
    uint32_t i;
    uint32_t prev_block[2];

    prev_block[0] = iv[0];
    prev_block[1] = iv[1];

    for (i = 0; i < block_count; i += 2)
    {

        xtea_encrypt(prev_block, key);

        data[i    ] ^= prev_block[0];
        data[i + 1] ^= prev_block[1];
    }
}

void 
xtea_decrypt_ofb(uint32_t* data, uint32_t block_count, uint32_t key[4], uint32_t iv[2])
{
    uint32_t i;
    uint32_t prev_block[2];

    prev_block[0] = iv[0];
    prev_block[1] = iv[1];

    for (i = 0; i < block_count; i += 2)
    {

        xtea_encrypt(prev_block, key);

        data[i    ] ^= prev_block[0];
        data[i + 1] ^= prev_block[1];
    }
}

void 
xtea_encrypt_pcbc(uint32_t* data, uint32_t block_count, uint32_t key[4], uint32_t iv[2])
{
    uint32_t i;
    uint32_t prev_block[2];
    uint32_t ptext_block[2];

    prev_block[0] = iv[0];
    prev_block[1] = iv[1];

    for (i = 0; i < block_count; i += 2)
    {

        ptext_block[0] = data[i    ];
        ptext_block[1] = data[i + 1];

        data[i    ] ^= prev_block[0];
        data[i + 1] ^= prev_block[1];

        xtea_encrypt(&data[i], key);

        prev_block[0] = ptext_block[0] ^ data[i    ];
        prev_block[1] = ptext_block[1] ^ data[i + 1];
    }
}

void 
xtea_decrypt_pcbc(uint32_t* data, uint32_t block_count, uint32_t key[4], uint32_t iv[2])
{
    uint32_t i;
    uint32_t prev_block[2];
    uint32_t ctext_block[2];

    prev_block[0] = iv[0];
    prev_block[1] = iv[1];

    for (i = 0; i < block_count; i+= 2)
    {

        ctext_block[0] = data[i    ];
        ctext_block[1] = data[i + 1];

        xtea_decrypt(&data[i], key);

        data[i    ] ^= prev_block[0];
        data[i + 1] ^= prev_block[1];

        prev_block[0] = ctext_block[0] ^ data[i    ];
        prev_block[1] = ctext_block[1] ^ data[i + 1];
    }
}
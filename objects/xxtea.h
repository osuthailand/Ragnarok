#ifndef XXTEA_HPP_GUARD
#define XXTEA_HPP_GUARD

// port of XXTea code from Osz2Decryptor to C
// by r0neko

#include <stdint.h>
#include <stddef.h>
#include <string.h>

#define MAX 16
#define MAX_BYTES (MAX * 4)
#define TEA_DELTA 0x9e3779b9

struct XXTea {
    uint8_t _key[MAX];
    uint32_t _n;
};

void XXTea_Init(struct XXTea* tea, const uint8_t* key);
void XXTea_EncryptDecryptXXTea(struct XXTea* tea, char* buffer, int bufferLength, int encrypt);
void XXTea_EncryptWords(uint32_t* v, uint8_t* key, uint32_t n);
void XXTea_DecryptWords(uint32_t* v, uint8_t* key, uint32_t n);

#endif
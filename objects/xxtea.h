#ifndef XXTEA_HPP_GUARD
#define XXTEA_HPP_GUARD

// port of XXTea code from Osz2Decryptor to C
// by r0neko

#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>

#define MAX 16
#define MAX_BYTES (MAX * 4)
#define TEA_DELTA 0x9e3779b9

void XTea_Decrypt(const uint32_t* key, const void* src, void* dst, int size);
void XTea_DecryptWords(uint32_t* dst_src, const uint32_t* key);

void XXTea_Decrypt(const uint32_t* key, const void* src, void* dst, int size);
void XXTea_Encrypt(const uint32_t* key, const void* src, void* dst, int size);

void XXTea_EncryptWords(uint32_t* src_dst, const uint32_t* key, uint32_t n);
void XXTea_DecryptWords(uint32_t* src_dst, const uint32_t* key, uint32_t n);

void SimpleCryptor_EncryptBytes(const uint32_t* key, const void* src, uint8_t* dst, int size);
void SimpleCryptor_DecryptBytes(const uint32_t* key, const void* src, uint8_t* dst, int size);

// utils functions
uint8_t RotateLeft(uint8_t val, uint8_t n);
uint8_t RotateRight(uint8_t val, uint8_t n);

#endif
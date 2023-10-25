#include "xxtea.h"

// port of XXTea code from Osz2Decryptor to C
// by r0neko

void XXTea_Encrypt(const uint32_t* key, const void* src, void* dst, int size) {
	uint32_t fullWordCount = (uint32_t)size / MAX_BYTES;
	uint32_t leftOver = (uint32_t)size % MAX_BYTES;

	uint32_t* uBufferPtr = (uint32_t*)dst;

	uint32_t _n = MAX;
	uint32_t rounds = 6 + 52 / _n;

	// copy the source data to the destination, if the source is not the same.
	if (src != dst) {
		memcpy(dst, src, size);
	}

	for (uint32_t wordCount = 0; wordCount < fullWordCount; wordCount++)
	{
		XXTea_EncryptWords(uBufferPtr, key, _n);
		uBufferPtr += MAX;
	}

	if (leftOver == 0)
		return;

	_n = leftOver / 4;
	if (_n > 1)
	{
		XXTea_EncryptWords(uBufferPtr, key, _n);

		leftOver -= _n * 4;
		if (leftOver == 0)
			return;
	}

	SimpleCryptor_EncryptBytes(key, ((uint8_t*)src + size - leftOver), ((uint8_t*)dst + size - leftOver), leftOver);
}

void XXTea_Decrypt(const uint32_t* key, const void* src, void* dst, int size) {
	uint32_t fullWordCount = (uint32_t) size / MAX_BYTES;
	uint32_t leftOver = (uint32_t) size % MAX_BYTES;

	uint32_t* uBufferPtr = (uint32_t*) dst;

	uint32_t _n = MAX;
	uint32_t rounds = 6 + 52 / _n;

	// copy the source data to the destination, if the source is not the same.
	if (src != dst) {
		memcpy(dst, src, size);
	}

	for (uint32_t wordCount = 0; wordCount < fullWordCount; wordCount++)
	{
		uint32_t y, z, sum;
		uint32_t p, e;
		sum = rounds * TEA_DELTA;

		y = uBufferPtr[0];
		do
		{
			e = (sum >> 2) & 3;
			for (p = MAX - 1; p > 0; p--)
			{
				z = uBufferPtr[p - 1];
				y = uBufferPtr[p] -= (((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4))) ^
					((sum ^ y) + (key[(p & 3) ^ e] ^ z));
			}

			z = uBufferPtr[MAX - 1];
			y = uBufferPtr[0] -= (((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4))) ^
				((sum ^ y) + (key[(p & 3) ^ e] ^ z));
		} while ((sum -= TEA_DELTA) != 0);

		uBufferPtr += MAX;
	}

	if (leftOver == 0)
		return;

	_n = leftOver / 4;
	if (_n > 1)
	{
		XXTea_DecryptWords(uBufferPtr, key, _n);

		leftOver -= _n * 4;
		if (leftOver == 0)
			return;
	}

	SimpleCryptor_DecryptBytes(key, ((uint8_t*)src + size - leftOver), ((uint8_t*) dst + size - leftOver), leftOver);
}

void XXTea_EncryptWords(uint32_t* src_dst, const uint32_t* key, uint32_t n) {
	uint32_t y, z, sum;
	uint32_t p, e;
	uint32_t rounds = 6 + 52 / n;

	sum = 0;
	z = src_dst[n - 1];

	do
	{
		sum += TEA_DELTA;
		e = (sum >> 2) & 3;
		for (p = 0; p < n - 1; p++)
		{
			y = src_dst[p + 1];
			z = src_dst[p] += (((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4))) ^ ((sum ^ y) + (key[(p & 3) ^ e] ^ z));
		}

		y = src_dst[0];
		z = src_dst[n - 1] += (((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4))) ^ ((sum ^ y) + (key[(p & 3) ^ e] ^ z));
	} while (--rounds > 0);
}

void XXTea_DecryptWords(uint32_t* src_dst, const uint32_t* key, uint32_t n) {
	uint32_t y, z, sum;
	uint32_t p, e;
	uint32_t rounds = 6 + 52 / n;

	sum = rounds * TEA_DELTA;
	y = src_dst[0];

	do
	{
		e = (sum >> 2) & 3;
		for (p = n - 1; p > 0; p--)
		{
			z = src_dst[p - 1];
			y = src_dst[p] -= (((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4))) ^ ((sum ^ y) + (key[(p & 3) ^ e] ^ z));
		}

		z = src_dst[n - 1];
		y = src_dst[0] -= (((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4))) ^ ((sum ^ y) + (key[(p & 3) ^ e] ^ z));
	} while ((sum -= TEA_DELTA) != 0);
}

void SimpleCryptor_DecryptBytes(const uint32_t* key, const void* src, uint8_t* dst, int size) {
	uint8_t* byteKey = (uint8_t*)key;
	uint32_t prevEncrypted = 0;

	// copy the source data to the destination, if the source is not the same.
	if (src != dst) {
		memcpy(dst, src, size);
	}

	for (int i = 0; i < size; i++)
	{
		char tmpE = dst[i];
		dst[i] = RotateLeft(dst[i], (uint8_t)((~prevEncrypted) % 7));
		dst[i] ^= RotateLeft(byteKey[15 - i % 16], (uint8_t)((prevEncrypted + size - i) % 7));
		dst[i] = (dst[i] - (byteKey[i % 16] >> 2)) % 256;

		prevEncrypted = tmpE;
	}
}

void SimpleCryptor_EncryptBytes(const uint32_t* key, const void* src, uint8_t* dst, int size) {
	uint8_t* byteKey = (uint8_t*)key;
	uint32_t prevEncrypted = 0;

	// copy the source data to the destination, if the source is not the same.
	if (src != dst) {
		memcpy(dst, src, size);
	}

	for (int i = 0; i < size; i++)
	{
		dst[i] = (dst[i] + (byteKey[i % 16] >> 2)) % 256;
		dst[i] ^= RotateLeft(byteKey[15 - i % 16], (prevEncrypted + size - i) % 7);
		dst[i] = RotateRight(dst[i], ((~prevEncrypted) % 7));

		prevEncrypted = dst[i];
	}
}

uint8_t RotateLeft(uint8_t val, uint8_t n) {
	return ((val << n) | (val >> (8 - n)));
}

uint8_t RotateRight(uint8_t val, uint8_t n)
{
	return ((val >> n) | (val << (8 - n)));
}

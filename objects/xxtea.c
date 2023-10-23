#include "xxtea.h"

// port of XXTea code from Osz2Decryptor to C
// by r0neko
// modified accordingly by aoba

void XXTea_Init(struct XXTea* tea, const uint8_t* key) {
	memcpy(tea->_key, key, MAX);
}

void XXTea_EncryptDecryptXXTea(struct XXTea* tea, char* buffer, int bufferLength, int encrypt) {
	int fullWordCount = bufferLength / (MAX_BYTES);
	int leftOver = bufferLength % (MAX_BYTES);
	tea->_n = MAX;
	int rounds = 6 + 52 / tea->_n;
	if (encrypt) {
		for (int wordCount = 0; wordCount < fullWordCount; wordCount++) {
			XXTea_EncryptWords((uint32_t*)&buffer, tea->_key, MAX);
			buffer += MAX;
		}
	}
	else {
		for (int wordCount = 0; wordCount < fullWordCount; wordCount++) {
			uint32_t y, z, sum;
			uint32_t p, e;
			sum = rounds * TEA_DELTA;
			y = buffer[0];
			do {
				e = (sum >> 2) & 3;
				for (p = MAX - 1; p > 0; p--) {
					z = buffer[p - 1];
                    y = buffer[p] -= (((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4))) ^ ((sum ^ y) + (tea->_key[(p & 3) ^ e] ^ z));
				}
				z = buffer[MAX - 1];
                y = buffer[0] -= (((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4))) ^ ((sum ^ y) + (tea->_key[(p & 3) ^ e] ^ z));
			} while ((sum -= TEA_DELTA) != 0);
			buffer += MAX;
		}
	}

	if (leftOver == 0)
		return;

	tea->_n = leftOver / 4;
	if (tea->_n > 1) {
		if (encrypt) {
			// why tf isn't my buffer ref working :skull:
			XXTea_EncryptWords((uint32_t*)&buffer, tea->_key, tea->_n);
		}
		else {
			XXTea_DecryptWords((uint32_t*)&buffer, tea->_key, tea->_n);
		}

		leftOver -= tea->_n * 4;
		if (leftOver == 0)
			return;
	}

	char prevEncrypted = 0;
	if (encrypt) {
		for (int i = 0; i < bufferLength; i++) {
			buffer[i] = (char)(buffer[i] + (tea->_key[i % MAX] >> 2)) % 256;
			buffer[i] ^= (tea->_key[(MAX - 1) - i % MAX] << (prevEncrypted + bufferLength - i) % 7);
			buffer[i] = (buffer[i] >> (~(char)prevEncrypted % 7)) | (buffer[i] << (7 - (~(char)prevEncrypted % 7)));

			prevEncrypted = buffer[i];
		}
	}
	else {
		for (int i = 0; i < bufferLength; i++) {
			char tmpE = buffer[i];
			buffer[i] = (buffer[i] << (~(char)prevEncrypted % 7)) | (buffer[i] >> (7 - (~(char)prevEncrypted % 7)));
			buffer[i] ^= (tea->_key[(MAX - 1) - i % MAX] << ((prevEncrypted + bufferLength - i) % 7));
			buffer[i] = (char)((buffer[i] - (tea->_key[i % MAX] >> 2)) % 256);

			prevEncrypted = tmpE;
		}
	}
}

void XXTea_EncryptWords(uint32_t* v, uint8_t* key, uint32_t n) {
	uint32_t y, z, sum;
	uint32_t p, e;
	int rounds = 6 + 52 / n;
	sum = 0;
	z = v[n - 1];
	do {
		sum += TEA_DELTA;
		e = (sum >> 2) & 3;
		for (p = 0; p < n - 1; p++) {
			y = v[p + 1];
			z = v[p] += (((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4))) ^ ((sum ^ y) + (key[(p & 3) ^ e] ^ z));
		}
		y = v[0];
		z = v[n - 1] += (((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4))) ^ ((sum ^ y) + (key[(p & 3) ^ e] ^ z));
	} while (--rounds > 0);
}

void XXTea_DecryptWords(uint32_t* v, uint8_t* key, uint32_t n) {
	uint32_t y, z, sum;
	uint32_t p, e;
	int rounds = 6 + 52 / n;
	sum = rounds * TEA_DELTA;
	y = v[0];
	do {
		e = (sum >> 2) & 3;
		for (p = n - 1; p > 0; p--) {
			z = v[p - 1];
			y = v[p] -= (((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4))) ^ ((sum ^ y) + (key[(p & 3) ^ e] ^ z));
		}

		z = v[n - 1];
		y = v[0] -= (((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4))) ^ ((sum ^ y) + (key[(p & 3) ^ e] ^ z));
	} while ((sum -= TEA_DELTA) != 0);
}
#ifndef LINK_PROTOCOL_H
#define LINK_PROTOCOL_H

#include <Arduino.h>
#include <string.h>

namespace Link {

constexpr uint8_t FEND  = 0xC0;
constexpr uint8_t FESC  = 0xDB;
constexpr uint8_t TFEND = 0xDC;
constexpr uint8_t TFESC = 0xDD;

constexpr uint8_t META = 1;
constexpr uint8_t DATA = 2;
constexpr uint8_t END  = 3;

constexpr uint16_t CHUNK = 128;
constexpr uint16_t HEADER_SIZE = 18;
constexpr uint16_t APP_MAX = HEADER_SIZE + CHUNK + 4;
constexpr uint16_t AX_SIZE = 16;

constexpr uint32_t MAX_FILE_SIZE = 4UL * 1024UL * 1024UL;
constexpr uint32_t MAX_CHUNKS =
    (MAX_FILE_SIZE + CHUNK - 1UL) / CHUNK;

inline uint16_t get16(const uint8_t *p) {
  return uint16_t(p[0]) | (uint16_t(p[1]) << 8);
}

inline uint32_t get32(const uint8_t *p) {
  return uint32_t(p[0])
       | (uint32_t(p[1]) << 8)
       | (uint32_t(p[2]) << 16)
       | (uint32_t(p[3]) << 24);
}

inline void put32(uint8_t *p, uint32_t value) {
  for (uint8_t i = 0; i < 4; ++i) {
    p[i] = uint8_t(value >> (8 * i));
  }
}

// CRC-32/ISO-HDLC, compatible with Python zlib.crc32().
inline uint32_t crc32(const uint8_t *data, uint16_t length) {
  uint32_t crc = 0xFFFFFFFFUL;

  for (uint16_t i = 0; i < length; ++i) {
    crc ^= data[i];

    for (uint8_t bit = 0; bit < 8; ++bit) {
      crc = (crc >> 1)
          ^ ((crc & 1UL) ? 0xEDB88320UL : 0UL);
    }
  }

  return crc ^ 0xFFFFFFFFUL;
}

struct App {
  uint8_t type;
  uint32_t id;
  uint32_t sequence;
  uint32_t total;
  uint16_t length;
  const uint8_t *payload;
  uint32_t crc;
};

inline bool readApp(const uint8_t *p, uint16_t n, App &a) {
  if (n < HEADER_SIZE + 4 || n > APP_MAX) return false;
  if (p[0] != 'C' || p[1] != 'S' || p[2] != 1) return false;

  a.type = p[3];
  a.id = get32(p + 4);
  a.sequence = get32(p + 8);
  a.total = get32(p + 12);
  a.length = get16(p + 16);
  a.payload = p + HEADER_SIZE;

  if (a.id == 0 || a.total > MAX_CHUNKS) return false;
  if (a.length > CHUNK) return false;
  if (n != HEADER_SIZE + a.length + 4) return false;

  a.crc = get32(p + n - 4);
  if (a.crc != crc32(p, n - 4)) return false;

  if (a.type == META) {
    if (a.sequence != 0 || a.length < 12) return false;

    uint32_t fileSize = get32(a.payload);
    uint16_t chunkSize = get16(a.payload + 8);
    uint8_t nameLength = a.payload[10];

    if (fileSize > MAX_FILE_SIZE) return false;
    if (chunkSize != CHUNK) return false;
    if (nameLength < 1 || nameLength > 48) return false;
    if (a.length != uint16_t(11 + nameLength)) return false;

    uint32_t expectedTotal =
        (fileSize + CHUNK - 1UL) / CHUNK;

    return a.total == expectedTotal;
  }

  if (a.type == DATA) {
    if (a.total == 0 || a.sequence >= a.total) return false;
    if (a.length == 0) return false;

    // Every packet except the last must be full-sized.
    if (a.sequence + 1UL < a.total && a.length != CHUNK) {
      return false;
    }

    return true;
  }

  if (a.type == END) {
    return a.length == 0 && a.sequence == a.total;
  }

  return false;
}

inline void writeEscaped(Stream &out, uint8_t value) {
  if (value == FEND) {
    out.write(FESC);
    out.write(TFEND);
  } else if (value == FESC) {
    out.write(FESC);
    out.write(TFESC);
  } else {
    out.write(value);
  }
}

// KISS port 0, command 0. Input excludes the command byte.
inline void sendKiss(Stream &out,
                     const uint8_t *data,
                     uint16_t length) {
  out.write(FEND);
  writeEscaped(out, 0x00);

  for (uint16_t i = 0; i < length; ++i) {
    writeEscaped(out, data[i]);
  }

  out.write(FEND);
}

// CAP includes the KISS command byte.
// Returned data remains valid until the next feed() calls overwrite it.
template <uint16_t CAP>
class KissRx {
 public:
  uint8_t data[CAP];
  uint16_t length = 0;
  uint32_t rejected = 0;

  void reset() {
    used = 0;
    length = 0;
    active = false;
    escaped = false;
    bad = false;
    lastByte = millis();
  }

  bool feed(uint8_t value) {
    uint32_t now = millis();

    if (active && (used || escaped || bad)
        && uint32_t(now - lastByte) > 3000UL) {
      ++rejected;
      reset();
    }

    lastByte = now;

    if (value == FEND) {
      bool ready = active && !bad && !escaped && used > 0;

      if (active && (bad || escaped)) {
        ++rejected;
      }

      length = ready ? used : 0;
      used = 0;
      active = true;
      escaped = false;
      bad = false;

      return ready;
    }

    if (!active || bad) return false;

    if (escaped) {
      if (value == TFEND) {
        value = FEND;
      } else if (value == TFESC) {
        value = FESC;
      } else {
        bad = true;
        return false;
      }

      escaped = false;
    } else if (value == FESC) {
      escaped = true;
      return false;
    }

    if (used >= CAP) {
      bad = true;
      return false;
    }

    data[used++] = value;
    return false;
  }

 private:
  uint16_t used = 0;
  bool active = false;
  bool escaped = false;
  bool bad = false;
  uint32_t lastByte = 0;
};

// Fixed AX.25 UI command, no digipeaters:
// destination GROUND-0, source CUBSAT-0.
inline void makeAxHeader(uint8_t *out) {
  const char destination[] = "GROUND";
  const char source[] = "CUBSAT";

  for (uint8_t i = 0; i < 6; ++i) {
    out[i] = uint8_t(destination[i] << 1);
    out[7 + i] = uint8_t(source[i] << 1);
  }

  out[6] = 0xE0;   // C=1, reserved=11, SSID=0, extension=0
  out[13] = 0x61;  // C=0, reserved=11, SSID=0, extension=1
  out[14] = 0x03;  // UI
  out[15] = 0xF0;  // No layer 3 protocol
}

inline bool validAxHeader(const uint8_t *p) {
  uint8_t expected[AX_SIZE];
  makeAxHeader(expected);
  return memcmp(p, expected, AX_SIZE) == 0;
}

// Local ACK only: "AK" + application CRC32 + ACK CRC32.
// This is not transmitted over RF.
inline void makeAck(uint8_t *out, uint32_t token) {
  out[0] = 'A';
  out[1] = 'K';
  put32(out + 2, token);
  put32(out + 6, crc32(out, 6));
}

inline bool validAck(const uint8_t *p,
                     uint16_t n,
                     uint32_t token) {
  return n == 10
      && p[0] == 'A'
      && p[1] == 'K'
      && get32(p + 2) == token
      && get32(p + 6) == crc32(p, 6);
}

}  // namespace Link

#endif
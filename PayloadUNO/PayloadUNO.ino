#include <SoftwareSerial.h>
#include "LinkProtocol.h"

using namespace Link;

//RX, TX
SoftwareSerial comm(10, 11);

KissRx<APP_MAX + 1> usbRx;
KissRx<11> ackRx;

constexpr uint32_t LOCAL_ACK_TIMEOUT_MS = 4000UL;

bool forwardToComm(const uint8_t *packet,
                   uint16_t length,
                   uint32_t token) {
  // Remove stale local ACK bytes.
  while (comm.available()) {
    comm.read();
  }

  ackRx.reset();

  // Avoid USB TX interrupts while SoftwareSerial is transmitting.
  Serial.flush();

  sendKiss(comm, packet, length);

  uint32_t started = millis();

  while (uint32_t(millis() - started) < LOCAL_ACK_TIMEOUT_MS) {
    while (comm.available()) {
      uint8_t value = uint8_t(comm.read());

      if (!ackRx.feed(value)) continue;

      if (ackRx.length == 11
          && ackRx.data[0] == 0x00
          && validAck(ackRx.data + 1, 10, token)) {
        return true;
      }
    }
  }

  return false;
}

void setup() {
  Serial.begin(115200);
  comm.begin(9600);
  comm.listen();

  usbRx.reset();
  ackRx.reset();

  Serial.println(F("READY UNO1"));
}

void loop() {
  while (Serial.available()) {
    uint8_t value = uint8_t(Serial.read());

    if (!usbRx.feed(value)) continue;

    if (usbRx.length < 2 || usbRx.data[0] != 0x00) {
      Serial.println(F("ERR BAD_KISS_COMMAND"));
      continue;
    }

    App app;

    if (!readApp(usbRx.data + 1, usbRx.length - 1, app)) {
      Serial.println(F("ERR BAD_APP"));
      continue;
    }

    bool ok = forwardToComm(
        usbRx.data + 1,
        usbRx.length - 1,
        app.crc
    );

    if (ok) {
      Serial.print(F("OK "));
      Serial.println((unsigned long)app.crc);
    } else {
      Serial.println(F("ERR LOCAL_TIMEOUT"));
    }
  }
}
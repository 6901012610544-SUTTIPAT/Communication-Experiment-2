#include "LinkProtocol.h"

using namespace Link;

KissRx<APP_MAX + 1> payloadRx;

// Conservative initial spacing for bench testing.
// Tune only after measuring loss and throughput.
constexpr uint16_t RF_GAP_MS = 250;

void setup() {
  Serial.begin(115200);
  Serial1.begin(9600);  // HC-12
  Serial2.begin(9600);  // UNO

  payloadRx.reset();

  Serial.println(F("READY COMM1"));
}

void loop() {
  while (Serial2.available()) {
    uint8_t value = uint8_t(Serial2.read());

    if (!payloadRx.feed(value)) continue;

    if (payloadRx.length < 2 || payloadRx.data[0] != 0x00) {
      continue;
    }

    const uint8_t *packet = payloadRx.data + 1;
    uint16_t packetLength = payloadRx.length - 1;

    App app;

    if (!readApp(packet, packetLength, app)) {
      // No ACK: UNO/PC will time out and retry.
      continue;
    }

    uint8_t axFrame[AX_SIZE + APP_MAX];

    makeAxHeader(axFrame);
    memcpy(axFrame + AX_SIZE, packet, packetLength);

    sendKiss(Serial1, axFrame, AX_SIZE + packetLength);

    // Wait until the UART has physically transmitted its queued bytes.
    // This does NOT confirm RF delivery.
    Serial1.flush();

    delay(RF_GAP_MS);

    uint8_t ack[10];
    makeAck(ack, app.crc);

    sendKiss(Serial2, ack, sizeof(ack));
    Serial2.flush();
  }
}
#include "LinkProtocol.h"

using namespace Link;

KissRx<1 + AX_SIZE + APP_MAX> radioRx;

uint32_t acceptedPackets = 0;
uint32_t rejectedPackets = 0;
uint32_t lastStatistics = 0;

void printHex(const uint8_t *data, uint16_t length) {
  const char digits[] = "0123456789ABCDEF";

  for (uint16_t i = 0; i < length; ++i) {
    Serial.write(digits[data[i] >> 4]);
    Serial.write(digits[data[i] & 0x0F]);
  }
}

void tab() {
  Serial.write('\t');
}

void outputApplication(const App &app) {
  if (app.type == META) {
    Serial.print(F("META"));
    tab();
    Serial.print((unsigned long)app.id);
    tab();
    Serial.print((unsigned long)app.total);
    tab();
    Serial.print((unsigned long)get32(app.payload));
    tab();
    Serial.print((unsigned long)get32(app.payload + 4));
    tab();
    Serial.print(get16(app.payload + 8));
    tab();

    uint8_t nameLength = app.payload[10];
    printHex(app.payload + 11, nameLength);
    Serial.println();

  } else if (app.type == DATA) {
    Serial.print(F("DATA"));
    tab();
    Serial.print((unsigned long)app.id);
    tab();
    Serial.print((unsigned long)app.sequence);
    tab();
    Serial.print((unsigned long)app.total);
    tab();
    Serial.print(app.length);
    tab();
    printHex(app.payload, app.length);
    Serial.println();

  } else if (app.type == END) {
    Serial.print(F("END"));
    tab();
    Serial.print((unsigned long)app.id);
    tab();
    Serial.println((unsigned long)app.total);
  }
}

void processRadioFrame() {
  // 1 KISS command + 16 AX.25 header + application packet.
  if (radioRx.length < 1 + AX_SIZE + HEADER_SIZE + 4
      || radioRx.data[0] != 0x00) {
    ++rejectedPackets;
    return;
  }

  const uint8_t *axFrame = radioRx.data + 1;

  if (!validAxHeader(axFrame)) {
    ++rejectedPackets;
    return;
  }

  const uint8_t *application = axFrame + AX_SIZE;
  uint16_t applicationLength = radioRx.length - 1 - AX_SIZE;

  App app;

  if (!readApp(application, applicationLength, app)) {
    ++rejectedPackets;
    return;
  }

  ++acceptedPackets;
  outputApplication(app);
}

void setup() {
  Serial.begin(115200);
  Serial1.begin(9600);

  radioRx.reset();

  Serial.println(F("READY GS1"));
}

void loop() {
  while (Serial1.available()) {
    uint8_t value = uint8_t(Serial1.read());

    if (radioRx.feed(value)) {
      processRadioFrame();
    }
  }

  if (uint32_t(millis() - lastStatistics) >= 5000UL) {
    lastStatistics = millis();

    Serial.print(F("STAT"));
    tab();
    Serial.print((unsigned long)acceptedPackets);
    tab();
    Serial.print((unsigned long)rejectedPackets);
    tab();
    Serial.println((unsigned long)radioRx.rejected);
  }
}
#include <Arduino.h>

/* ================================================================
   AD7606 MULTI-ADC PARALLEL - ARDUINO GIGA
   ================================================================ */

#define NUM_ADC               2
#define SNAPSHOT_MODE         0
#define BOARD_RST_ACTIVE_HIGH 1

// -------------------- Data Bus --------------------
static const uint8_t DB_PINS[16] = {
  22,23,24,25,26,27,28,29,
  30,31,32,33,34,35,36,37
};

// -------------------- Shared Control Pins --------------------
static const uint8_t PIN_OS0   = 2;
static const uint8_t PIN_OS1   = 3;
static const uint8_t PIN_OS2   = 4;
static const uint8_t PIN_RANGE = 5;
static const uint8_t PIN_CVA   = 6;
static const uint8_t PIN_CVB   = 7;
static const uint8_t PIN_RST   = 8;
static const uint8_t PIN_RD    = 9;
static const uint8_t PIN_FRST  = 11;

// -------------------- Per-ADC CS/BUSY --------------------
static uint8_t CS_PINS[NUM_ADC];
static uint8_t BUSY_PINS[NUM_ADC];

// -------------------- Helpers --------------------
static inline void pulseLow(uint8_t pin, uint16_t low_us = 1) {
  digitalWrite(pin, LOW);
  delayMicroseconds(low_us);
  digitalWrite(pin, HIGH);
}

void ad7606_reset() {
#if BOARD_RST_ACTIVE_HIGH
  digitalWrite(PIN_RST, HIGH);
  delay(10);
  digitalWrite(PIN_RST, LOW);
#else
  digitalWrite(PIN_RST, LOW);
  delay(10);
  digitalWrite(PIN_RST, HIGH);
#endif
  delay(10);
}

static inline void trigger_conversion_sync() {
  digitalWrite(PIN_CVA, LOW);
  delayMicroseconds(2);
  digitalWrite(PIN_CVA, HIGH);
}

uint16_t read_bus16() {
  uint16_t v = 0;
  digitalWrite(PIN_RD, LOW);
  delayMicroseconds(1);

  for (int i = 0; i < 16; i++) {
    if (digitalRead(DB_PINS[i])) v |= (1u << i);
  }

  digitalWrite(PIN_RD, HIGH);
  return v;
}

/* ================================================================
   Voltage scaling: -3.3V → 3.3V (BIPOLAR OUTPUT FORMAT)
   ================================================================ */
float rawToVoltageSigned(uint16_t raw) {
  int16_t s = (int16_t)raw;          // preserve sign
  return (s * 5.0f) / 32768.0f;      // ±5V range
}

// Placeholder (future sensor)
float humidity_percent = 0.00f;

// Wait until ALL BUSY pins are LOW
bool wait_all_busy_low(uint32_t timeout_us = 200000) {
  uint32_t t0 = micros();
  while (true) {
    bool any_busy = false;
    for (int i = 0; i < NUM_ADC; i++) {
      if (digitalRead(BUSY_PINS[i]) == HIGH) {
        any_busy = true;
        break;
      }
    }
    if (!any_busy) return true;

    if (micros() - t0 > timeout_us) {
      Serial.println("BUSY TIMEOUT");
      return false;
    }
  }
}

// -------------------- Setup --------------------
void setup() {
  Serial.begin(115200);
  while (!Serial);

  for (int i = 0; i < 16; i++) pinMode(DB_PINS[i], INPUT);

  pinMode(PIN_OS0, OUTPUT);
  pinMode(PIN_OS1, OUTPUT);
  pinMode(PIN_OS2, OUTPUT);
  pinMode(PIN_RANGE, OUTPUT);
  pinMode(PIN_CVA, OUTPUT);
  pinMode(PIN_CVB, OUTPUT);
  pinMode(PIN_RST, OUTPUT);
  pinMode(PIN_RD, OUTPUT);
  pinMode(PIN_FRST, OUTPUT);

  digitalWrite(PIN_RD, HIGH);
  digitalWrite(PIN_FRST, HIGH);
  digitalWrite(PIN_CVA, HIGH);
  digitalWrite(PIN_CVB, HIGH);
  digitalWrite(PIN_RANGE, LOW);
  digitalWrite(PIN_OS0, LOW);
  digitalWrite(PIN_OS1, LOW);
  digitalWrite(PIN_OS2, LOW);

  for (int i = 0; i < NUM_ADC; i++) {
    CS_PINS[i]   = 38 + (i * 2);
    BUSY_PINS[i] = 39 + (i * 2);

    pinMode(CS_PINS[i], OUTPUT);
    pinMode(BUSY_PINS[i], INPUT);
    digitalWrite(CS_PINS[i], HIGH);
  }

  ad7606_reset();
}

// -------------------- Loop --------------------
void loop() {
  static bool done = false;
  if (SNAPSHOT_MODE && done) return;

  uint16_t raw[NUM_ADC][8];

  trigger_conversion_sync();

  if (!wait_all_busy_low()) {
    delay(500);
    return;
  }

  pulseLow(PIN_FRST, 1);

  for (int a = 0; a < NUM_ADC; a++) {
    digitalWrite(CS_PINS[a], LOW);
    delayMicroseconds(1);

    for (int ch = 0; ch < 8; ch++) {
      raw[a][ch] = read_bus16();
    }

    digitalWrite(CS_PINS[a], HIGH);
  }

  /* ================================================================
     OUTPUT FORMAT:
     <d1 d2 d3 ... dX | humidity>
     ================================================================ */
  Serial.print("<");

  for (int a = 0; a < NUM_ADC; a++) {
    for (int ch = 0; ch < 8; ch++) {
      Serial.print(rawToVoltageSigned(raw[a][ch]), 4);
      Serial.print(" ");
    }
  }

  Serial.print("| ");
  Serial.print(humidity_percent, 2);
  Serial.println(">");

  done = true;
  delay(1000);
}

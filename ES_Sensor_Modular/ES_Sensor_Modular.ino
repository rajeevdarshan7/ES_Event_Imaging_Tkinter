#include <Arduino.h>

/* ================================================================
   AD7606 MULTI-ADC PARALLEL - ARDUINO GIGA
   ================================================================
   What you change:
     - NUM_ADC: number of AD7606 boards (CS/BUSY pairs on pins 38-53)
     - SNAPSHOT_MODE: 0 = continuous polling, 1 = take ONE capture then stop
     - BOARD_RST_ACTIVE_HIGH: set to 1 if your board reset is active-HIGH
                              (your old "working" code implies this is 1)

   Wiring (shared):
     DB0..DB15 : D22..D37
     OS0..OS2  : D2..D4
     RANGE     : D5
     CVA       : D6
     CVB       : D7 (we force HIGH)
     RST       : D8
     RD        : D9
     FRST      : D11

   Per ADC i (0-based):
     CS   = 38 + 2*i
     BUSY = 39 + 2*i
   Supports up to 8 ADCs using pins 38..53.
   ================================================================ */

#define NUM_ADC               2     // <<< change this (1..8)
#define SNAPSHOT_MODE         0     // <<< 0 = loop forever, 1 = single capture
#define BOARD_RST_ACTIVE_HIGH 1     // <<< RESET INVERTED

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

// Board-level reset polarity is configurable
void ad7606_reset() {
#if BOARD_RST_ACTIVE_HIGH
  // Board reset active-HIGH (matches your old working sequence)
  digitalWrite(PIN_RST, HIGH);
  delay(10);
  digitalWrite(PIN_RST, LOW);
#else
  // Chip-level reset active-LOW (datasheet)
  digitalWrite(PIN_RST, LOW);
  delay(10);
  digitalWrite(PIN_RST, HIGH);
#endif
  delay(10);
}

// Trigger ALL ADCs together (shared CVA). CVB is forced HIGH elsewhere.
static inline void trigger_conversion_sync() {
  digitalWrite(PIN_CVA, LOW);
  delayMicroseconds(2);
  digitalWrite(PIN_CVA, HIGH);
}

// Read 16-bit parallel data bus using RD (active LOW)
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

// Convert raw code to voltage for ±5V mode
float rawToVoltage(uint16_t raw) {
  int16_t s = (int16_t)raw;
  return (s * 5.0f) / 32768.0f;
}

// Wait until ALL BUSY pins are LOW, return true if success, false if timeout
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
      Serial.print("TIMEOUT BUSY: ");
      for (int i = 0; i < NUM_ADC; i++) {
        Serial.print(digitalRead(BUSY_PINS[i]));
        Serial.print(" ");
      }
      Serial.println();
      return false;
    }
  }
}

// -------------------- Setup --------------------
void setup() {
  Serial.begin(115200);
  while (!Serial);

  // Data bus inputs
  for (int i = 0; i < 16; i++) pinMode(DB_PINS[i], INPUT);

  // Shared control pins
  pinMode(PIN_OS0, OUTPUT);
  pinMode(PIN_OS1, OUTPUT);
  pinMode(PIN_OS2, OUTPUT);
  pinMode(PIN_RANGE, OUTPUT);
  pinMode(PIN_CVA, OUTPUT);
  pinMode(PIN_CVB, OUTPUT);
  pinMode(PIN_RST, OUTPUT);
  pinMode(PIN_RD, OUTPUT);
  pinMode(PIN_FRST, OUTPUT);

  // Safe idle states
  digitalWrite(PIN_RD, HIGH);
  digitalWrite(PIN_FRST, HIGH);
  digitalWrite(PIN_CVA, HIGH);
  digitalWrite(PIN_CVB, HIGH);      // CVB forced HIGH permanently
  digitalWrite(PIN_RANGE, LOW);     // ±5V
  digitalWrite(PIN_OS0, LOW);       // no oversampling
  digitalWrite(PIN_OS1, LOW);
  digitalWrite(PIN_OS2, LOW);

  // Per-ADC pins (CS/BUSY pairs on 38..53)
  for (int i = 0; i < NUM_ADC; i++) {
    CS_PINS[i]   = 38 + (i * 2);
    BUSY_PINS[i] = 39 + (i * 2);

    pinMode(CS_PINS[i], OUTPUT);
    pinMode(BUSY_PINS[i], INPUT);

    digitalWrite(CS_PINS[i], HIGH); // deselect
  }

  ad7606_reset();

  Serial.print("AD7606 multi-ADC started. NUM_ADC=");
  Serial.print(NUM_ADC);
  Serial.print(" SNAPSHOT_MODE=");
  Serial.print(SNAPSHOT_MODE);
  Serial.print(" RST_ACTIVE_HIGH=");
  Serial.println(BOARD_RST_ACTIVE_HIGH);
}

// -------------------- Loop --------------------
void loop() {
  static bool done = false;
  if (SNAPSHOT_MODE && done) return;

  uint16_t raw[NUM_ADC][8];

  // 1) Synchronous conversion trigger
  trigger_conversion_sync();

  // 2) Wait for all conversions to complete
  if (!wait_all_busy_low(200000)) {
    delay(500);
    return;
  }

  // 3) Align readout channel order (recommended)
  pulseLow(PIN_FRST, 1);

  // 4) Sequentially read each ADC (shared DB bus)
  for (int a = 0; a < NUM_ADC; a++) {
    digitalWrite(CS_PINS[a], LOW);
    delayMicroseconds(1);

    for (int ch = 0; ch < 8; ch++) {
      raw[a][ch] = read_bus16();
    }

    digitalWrite(CS_PINS[a], HIGH);
  }

  // 5) Print results
  for (int a = 0; a < NUM_ADC; a++) {
    Serial.print("ADC");
    Serial.print(a);
    Serial.print(": ");
    for (int ch = 0; ch < 8; ch++) {
      Serial.print(rawToVoltage(raw[a][ch]), 3);
      Serial.print("\t");
    }
    Serial.println();
  }
  Serial.println();

  done = true;

  // Polling rate
  delay(1000);
}

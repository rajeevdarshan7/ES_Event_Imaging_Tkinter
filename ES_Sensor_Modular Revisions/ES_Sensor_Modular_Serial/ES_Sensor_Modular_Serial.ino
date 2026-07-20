#include <Arduino.h>

/* ================================================================
   AD7606 MULTI-ADC PARALLEL ACQUISITION — ARDUINO GIGA

   Function:
   - Controls multiple AD7606 ADC devices sharing one 16-bit data bus.
   - Triggers all ADC channel groups at approximately the same time.
   - Reads eight channels from each ADC.
   - Converts signed ADC values into voltage values.
   - Sends framed measurement data through the serial port.
   - Supports continuous streaming, single snapshots and configurable
     output channel counts.

   Serial commands:
     start          Enable continuous data streaming.
     stop           Disable continuous data streaming.
     snapshot       Acquire and send one measurement frame.
     cfg <r> <c>    Set the number of values sent to r × c.
   ================================================================ */

// Total number of connected AD7606 devices.
#define NUM_ADC               5

// Set to 1 when the board reset signal is active-high.
// Set to 0 when the reset signal is active-low.
#define BOARD_RST_ACTIVE_HIGH 1

// ----------------------------------------------------------------
// Shared 16-bit parallel data bus
//
// DB_PINS[0] represents data bit 0.
// DB_PINS[15] represents data bit 15.
// ----------------------------------------------------------------
static const uint8_t DB_PINS[16] = {
  22, 23, 24, 25, 26, 27, 28, 29,
  30, 31, 32, 33, 34, 35, 36, 37
};

// ----------------------------------------------------------------
// Shared AD7606 control pins
//
// OS0–OS2 : Oversampling configuration.
// RANGE   : Input-range selection.
// CVA/CVB : Conversion-start signals for channel groups.
// RST     : ADC reset.
// RD      : Parallel data-read control.
// FRST    : First-data/channel-sequence synchronization.
// ----------------------------------------------------------------
static const uint8_t PIN_OS0   = 2;
static const uint8_t PIN_OS1   = 3;
static const uint8_t PIN_OS2   = 4;
static const uint8_t PIN_RANGE = 5;
static const uint8_t PIN_CVA   = 6;
static const uint8_t PIN_CVB   = 7;
static const uint8_t PIN_RST   = 8;
static const uint8_t PIN_RD    = 9;
static const uint8_t PIN_FRST  = 11;

// ----------------------------------------------------------------
// Per-ADC control pins
//
// Each ADC has:
// - an independent chip-select pin; and
// - an independent BUSY status pin.
// ----------------------------------------------------------------
static uint8_t CS_PINS[NUM_ADC];
static uint8_t BUSY_PINS[NUM_ADC];

// ----------------------------------------------------------------
// Runtime state
// ----------------------------------------------------------------

// True while continuous acquisition is enabled.
bool stream_enabled = false;

// Number of channel values included in each output frame.
// Five ADCs × eight channels gives a maximum of 40 values.
uint8_t output_count = NUM_ADC * 8;

// Placeholder for an auxiliary environmental measurement.
// This may later be updated using a separate humidity sensor.
float humidity_percent = 0.00f;

// ----------------------------------------------------------------
// Generate a configurable active-low pulse.
// ----------------------------------------------------------------
static inline void pulseLow(uint8_t pin, uint16_t low_us = 1) {
  digitalWrite(pin, LOW);
  delayMicroseconds(low_us);
  digitalWrite(pin, HIGH);
}

// ----------------------------------------------------------------
// Reset all ADC devices through the shared reset signal.
//
// The active level is selected using BOARD_RST_ACTIVE_HIGH.
// ----------------------------------------------------------------
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

  // Allow the ADC devices to stabilize after reset.
  delay(10);
}

// ----------------------------------------------------------------
// Trigger conversion for both AD7606 channel groups.
//
// CVA and CVB are asserted together so that all channels begin
// conversion at approximately the same time.
// ----------------------------------------------------------------
static inline void trigger_conversion_sync() {
  digitalWrite(PIN_CVA, LOW);
  digitalWrite(PIN_CVB, LOW);

  delayMicroseconds(2);

  digitalWrite(PIN_CVA, HIGH);
  digitalWrite(PIN_CVB, HIGH);
}

// ----------------------------------------------------------------
// Read one 16-bit value from the shared parallel data bus.
//
// The RD signal is asserted before sampling the sixteen data pins.
// Each sampled pin is placed into its corresponding bit position.
// ----------------------------------------------------------------
uint16_t read_bus16() {
  uint16_t value = 0;

  digitalWrite(PIN_RD, LOW);
  delayMicroseconds(1);

  for (int bit = 0; bit < 16; bit++) {
    if (digitalRead(DB_PINS[bit])) {
      value |= (1u << bit);
    }
  }

  digitalWrite(PIN_RD, HIGH);

  return value;
}

// ----------------------------------------------------------------
// Convert a raw 16-bit ADC word into a signed voltage.
//
// The raw word is interpreted as a signed 16-bit integer.
// The conversion assumes an AD7606 bipolar ±5 V input range.
// ----------------------------------------------------------------
float rawToVoltageSigned(uint16_t raw) {
  int16_t signed_raw = static_cast<int16_t>(raw);

  return (signed_raw * 5.0f) / 32768.0f;
}

// ----------------------------------------------------------------
// Wait until all ADC BUSY signals become LOW.
//
// A LOW BUSY signal indicates that the corresponding ADC has
// completed its conversion.
//
// Returns:
//   true  — conversion is complete;
//   false — timeout expired before completion.
// ----------------------------------------------------------------
bool wait_all_busy_low(uint32_t timeout_us = 200000) {
  uint32_t start_time = micros();

  while (true) {
    for (int adc = 0; adc < NUM_ADC; adc++) {
      if (digitalRead(BUSY_PINS[adc]) == HIGH) {
        if (micros() - start_time > timeout_us) {
          return false;
        }

        continue;
      }
    }

    return true;
  }
}

/* ================================================================
   ACQUIRE AND SEND ONE MEASUREMENT FRAME

   Acquisition sequence:
   1. Trigger all ADC conversions.
   2. Wait for conversion completion.
   3. Synchronize the first channel.
   4. Select each ADC individually.
   5. Read all eight channels from the selected ADC.
   6. Convert and transmit the configured number of values.
   ================================================================ */
void acquire_and_send_frame() {
  // Temporary storage for all ADC channel readings.
  uint16_t raw[NUM_ADC][8];

  // Start all ADC conversions.
  trigger_conversion_sync();

  // Do not read data if conversion did not complete in time.
  if (!wait_all_busy_low()) {
    return;
  }

  // Synchronize the output sequence to the first channel.
  pulseLow(PIN_FRST, 1);

  // Read each ADC individually from the shared data bus.
  for (int adc = 0; adc < NUM_ADC; adc++) {
    // Select the current ADC.
    digitalWrite(CS_PINS[adc], LOW);
    delayMicroseconds(1);

    // Read all eight channels from the selected ADC.
    for (int channel = 0; channel < 8; channel++) {
      raw[adc][channel] = read_bus16();
    }

    // Release the current ADC from the shared bus.
    digitalWrite(CS_PINS[adc], HIGH);
  }

  // --------------------------------------------------------------
  // Output frame format:
  //
  // <value_1 value_2 ... value_n | humidity>
  //
  // Example:
  // <0.1250 -0.2500 1.5000 | 45.20>
  // --------------------------------------------------------------
  Serial.print("<");

  uint8_t printed = 0;

  // Transmit only the configured number of values.
  for (int adc = 0;
       adc < NUM_ADC && printed < output_count;
       adc++) {

    for (int channel = 0;
         channel < 8 && printed < output_count;
         channel++) {

      Serial.print(
        rawToVoltageSigned(raw[adc][channel]),
        4
      );

      Serial.print(" ");
      printed++;
    }
  }

  // Append the auxiliary humidity value.
  Serial.print("| ");
  Serial.print(humidity_percent, 2);

  // Complete the framed message.
  Serial.println(">");
}

// ----------------------------------------------------------------
// Arduino initialization
// ----------------------------------------------------------------
void setup() {
  // Start the serial interface used for commands and measurement data.
  Serial.begin(9600);

  // Wait for the USB serial interface to become available.
  while (!Serial);

  // Configure the shared parallel data bus as inputs.
  for (int bit = 0; bit < 16; bit++) {
    pinMode(DB_PINS[bit], INPUT);
  }

  // Configure shared control signals as outputs.
  pinMode(PIN_OS0, OUTPUT);
  pinMode(PIN_OS1, OUTPUT);
  pinMode(PIN_OS2, OUTPUT);
  pinMode(PIN_RANGE, OUTPUT);
  pinMode(PIN_CVA, OUTPUT);
  pinMode(PIN_CVB, OUTPUT);
  pinMode(PIN_RST, OUTPUT);
  pinMode(PIN_RD, OUTPUT);
  pinMode(PIN_FRST, OUTPUT);

  // Set inactive default states for the control signals.
  digitalWrite(PIN_RD, HIGH);
  digitalWrite(PIN_FRST, HIGH);
  digitalWrite(PIN_CVA, HIGH);
  digitalWrite(PIN_CVB, HIGH);

  // Assign and configure chip-select and BUSY pins.
  //
  // ADC 0: CS = 38, BUSY = 39
  // ADC 1: CS = 40, BUSY = 41
  // ADC 2: CS = 42, BUSY = 43
  // ADC 3: CS = 44, BUSY = 45
  // ADC 4: CS = 46, BUSY = 47
  for (int adc = 0; adc < NUM_ADC; adc++) {
    CS_PINS[adc]   = 38 + (adc * 2);
    BUSY_PINS[adc] = 39 + (adc * 2);

    pinMode(CS_PINS[adc], OUTPUT);
    pinMode(BUSY_PINS[adc], INPUT);

    // Keep every ADC deselected until it is being read.
    digitalWrite(CS_PINS[adc], HIGH);
  }

  // Reset all connected ADC devices.
  ad7606_reset();
}

// ----------------------------------------------------------------
// Main command and acquisition loop
// ----------------------------------------------------------------
void loop() {
  // --------------------------------------------------------------
  // Serial command handling
  // --------------------------------------------------------------
  if (Serial.available()) {
    String command = Serial.readStringUntil('\n');
    command.trim();

    if (command == "start") {
      // Enable continuous frame acquisition.
      stream_enabled = true;
    }
    else if (command == "stop") {
      // Disable continuous frame acquisition.
      stream_enabled = false;
    }
    else if (command == "snapshot") {
      // Acquire and transmit one frame immediately.
      acquire_and_send_frame();
    }
    else if (command.startsWith("cfg")) {
      // Configure the number of values included in each frame.
      //
      // Command format:
      // cfg <rows> <columns>
      //
      // Example:
      // cfg 4 4
      //
      // The example causes the device to transmit 16 values.
      int rows;
      int columns;

      if (
        sscanf(
          command.c_str(),
          "cfg %d %d",
          &rows,
          &columns
        ) == 2
      ) {
        output_count = constrain(
          rows * columns,
          1,
          NUM_ADC * 8
        );
      }
    }
  }

  // --------------------------------------------------------------
  // Continuous acquisition mode
  // --------------------------------------------------------------
  if (stream_enabled) {
    acquire_and_send_frame();

    // Current streaming period: approximately one frame per second.
    delay(1000);
  }
}

/**
  ADS1115 + 4xCD74HC4067 (64 channels) + Gantry stepper control + Homing
  - Uses Adafruit_ADS1X15 library for ADS1115
  - Assumes one ADS1115 at default 0x48
  - MUX chips share S0..S3 (change pins as needed)
  - Stepper driver with STEP/DIR pins (e.g. A4988/DRV8825). Motor power NOT from Arduino.
  - Limit switch wired to ground; using INPUT_PULLUP so switch closes to GND when hit.

  IMPORTANT: set STEPS_PER_MM to match your mechanical setup.
*/

#include <Wire.h>
#include <Adafruit_ADS1X15.h>

Adafruit_ADS1115 ads;
// ---------- Sensor ----------
const int ORI_RESO = 7.5
const int TARGET_RESO = 1.875

// ---------- MUX control pins ----------
const int S0 = 2;
const int S1 = 3;
const int S2 = 4;
const int S3 = 5;
const int MUX_CHANNELS = 9;
const int NUM_MUXES = 4; // 4 mux -> 36 channels total

// ---------- Stepper / Gantry pins ----------
const int X_STEP_PIN = 8;
const int X_DIR_PIN  = 9;
const int X_EN_PIN   = 10; // optional; set LOW to enable driver. If not used, set to -1 below.
const int X_LIMIT_PIN = 7; // home switch (wired to GND when pressed), using INPUT_PULLUP

// may need to change pin below
const int Y_STEP_PIN = 12;
const int Y_DIR_PIN  = 13;
const int Y_EN_PIN   = 14; // optional; set LOW to enable driver. If not used, set to -1 below.
const int Y_LIMIT_PIN = 11; // home switch (wired to GND when pressed), using INPUT_PULLUP

// ---------- Motion parameters (CHANGE to match your hardware) ----------
const float MAX_POSITION_MM = 50.0F;     // stop at 50 mm then reverse
const float MOVE_PER_SCAN_MM = 2.0F;     // move 2 mm after each full 64-channel scan

// Steps per mm: set according to motor steps, microstepping and leadscrew/belt pitch.
// Example: 200 steps/rev, microstepping 16x, lead screw 8 mm/rev -> (200*16)/8 = 400 steps/mm
const float STEPS_PER_MM = 400.0F;       // <-- ADJUST THIS TO YOUR MECHANICS

const unsigned int STEP_PULSE_US = 5;    // step pulse width (~5 us). Driver docs may require >= 1-2 us
const unsigned int STEP_DELAY_US = 600;  // delay between steps in microseconds (controls speed) - tune as needed

// Direction mapping:
// Set HOME_DIR to the Arduino level that moves the stage *toward* the home switch.
const uint8_t HOME_DIR = LOW;  // set to HIGH or LOW depending on your wiring
const uint8_t AWAY_DIR = (HOME_DIR == LOW) ? HIGH : LOW;

// Optional enable usage: if not used, set EN_PIN = -1
// If used and driver active low enable, pull LOW to enable.
const bool USE_ENABLE_PIN = true; // set false if no enable pin used

// ---------- Conversion constants ----------
const float LSB_MV = 0.125F; // ADS1115 with GAIN_ONE -> 0.125 mV per bit
float readings[36][25]; 

// current step position (signed), 0 at home; convert via STEPS_PER_MM
long x_currentSteps = 0;
long y_currentSteps = 0;

// ---------- Helper functions ----------
void setMuxChannel(uint8_t ch) {
  // ch: 0..15
  digitalWrite(S0, (ch & 0x01) ? HIGH : LOW);
  digitalWrite(S1, (ch & 0x02) ? HIGH : LOW);
  digitalWrite(S2, (ch & 0x04) ? HIGH : LOW);
  digitalWrite(S3, (ch & 0x08) ? HIGH : LOW);
}

// perform one step (single pulse) in 'dir' (HIGH/LOW)
void singleStep(uint8_t dir, bool is_x_axis) {

  if (is_x_axis) {

    digitalWrite(X_DIR_PIN, dir);
    // optional enable
    if (USE_ENABLE_PIN && X_EN_PIN >= 0) digitalWrite(X_EN_PIN, LOW); // enable driver (active low assumed)
    digitalWrite(X_STEP_PIN, HIGH);
    delayMicroseconds(STEP_PULSE_US);
    digitalWrite(X_STEP_PIN, LOW);
    delayMicroseconds(STEP_DELAY_US);

  }
  else {

    digitalWrite(Y_DIR_PIN, dir);
    // optional enable
    if (USE_ENABLE_PIN && Y_EN_PIN >= 0) digitalWrite(Y_EN_PIN, LOW); // enable driver (active low assumed)
    digitalWrite(Y_STEP_PIN, HIGH);
    delayMicroseconds(STEP_PULSE_US);
    digitalWrite(Y_STEP_PIN, LOW);
    delayMicroseconds(STEP_DELAY_US);

  }
  
}

// move steps_count steps in direction dir (HIGH/LOW)
void moveSteps(long steps_count, uint8_t dir, bool is_x_axis) {
  for (long i = 0; i < steps_count; ++i) {
    singleStep(dir, is_x_axis);
    if (is_x_axis) {
      // update currentSteps
      if (dir == AWAY_DIR) x_currentSteps += 1;
      else x_currentSteps -= 1;
    }
    else {
      // update currentSteps
      if (dir == AWAY_DIR) y_currentSteps += 1;
      else y_currentSteps -= 1;
    }
  }
}

// convert steps to mm
float stepsToMm(long steps) {
  return (float)steps / STEPS_PER_MM;
}

// convert mm to steps (rounded)
long mmToSteps(float mm) {
  return (long)round(mm * STEPS_PER_MM);
}

// homing procedure: move toward HOME_DIR until limit switch is triggered (LOW)
// then back off a small amount and set currentSteps = 0
void doHoming() {
  long backoffSteps = mmToSteps(2.0); // back off 2 mm
  Serial.println("Homing...");

  // Make sure limit switch isn't already pressed - if it is, back off a bit first
  if (digitalRead(X_LIMIT_PIN) == LOW) {
    // we're at the switch already, move away a little
    long backoff = mmToSteps(2.0); // back 2 mm
    Serial.println("Switch already triggered; backing off a bit...");
    moveSteps(backoff, AWAY_DIR, true);
    delay(50);
  }

  // Move toward home slowly until switch is pressed
  Serial.println("Moving toward home switch...");
  while (digitalRead(X_LIMIT_PIN) == HIGH) { // HIGH when open due to INPUT_PULLUP
    singleStep(HOME_DIR, true);
  }

  // switch pressed: back off a small amount to release switch
  Serial.println("Switch hit. Backing off and setting zero...");
  moveSteps(backoffSteps, AWAY_DIR, true);

  if (digitalRead(Y_LIMIT_PIN) == LOW) {
    // we're at the switch already, move away a little
    long backoff = mmToSteps(2.0); // back 2 mm
    Serial.println("Switch already triggered; backing off a bit...");
    moveSteps(backoff, AWAY_DIR, false);
    delay(50);
  }

  // Move toward home slowly until switch is pressed
  Serial.println("Moving toward home switch...");
  while (digitalRead(Y_LIMIT_PIN) == HIGH) { // HIGH when open due to INPUT_PULLUP
    singleStep(HOME_DIR, false);
  }

  // switch pressed: back off a small amount to release switch
  Serial.println("Switch hit. Backing off and setting zero...");
  moveSteps(backoffSteps, AWAY_DIR, false);

  // Set current position to zero
  x_currentSteps = 0;
  y_currentSteps = 0;
  Serial.println("Homing complete. Position set to 0 mm.");
}

// ---------- Setup & Loop ----------
void setup() {
  Serial.begin(115200);
  while (!Serial) { delay(1); } // wait for serial on some boards

  // Setup pins
  pinMode(S0, OUTPUT);
  pinMode(S1, OUTPUT);
  pinMode(S2, OUTPUT);
  pinMode(S3, OUTPUT);

  pinMode(X_STEP_PIN, OUTPUT);
  pinMode(X_DIR_PIN, OUTPUT);
  if (USE_ENABLE_PIN) {
    pinMode(X_EN_PIN, OUTPUT);
    digitalWrite(X_EN_PIN, LOW); // enable driver (assumes active low)
  }
  pinMode(X_LIMIT_PIN, INPUT_PULLUP); // switch to GND when pressed

  pinMode(Y_STEP_PIN, OUTPUT);
  pinMode(Y_DIR_PIN, OUTPUT);
  if (USE_ENABLE_PIN) {
    pinMode(Y_EN_PIN, OUTPUT);
    digitalWrite(Y_EN_PIN, LOW); // enable driver (assumes active low)
  }
  pinMode(Y_LIMIT_PIN, INPUT_PULLUP); // switch to GND when pressed

  // Initialize ADS1115
  if (!ads.begin()) {
    Serial.println("Failed to initialize ADS1115! Halting.");
    while (1) delay(1000);
  }
  ads.setDataRate(RATE_ADS1115_860SPS); // fastest (reduces scan time)
  ads.setGain(GAIN_ONE); // ±4.096V, LSB=0.125 mV

  // Home gantry on power-up
  doHoming();

  Serial.println("System ready.");
}

// Main scanning + motion loop
void loop() {
  // wait until start command from serial to invoke the scan process
  bool invoked = false;
  while (!invoked) {
    if (Serial.available() > 0) {
      char incomingByte = Serial.read();
      if (incomingByte == "start") {
        invoked = true;
      }
    }
  }

  // nest analog scan for statement into a dual for loop for moving the 2 gantries X and Y
  for (int i = 0; i < (int)(MAX_POSITION_MM/MOVE_PER_SCAN_MM); i++) {
    for (int j = 0; j < (int)(MAX_POSITION_MM/MOVE_PER_SCAN_MM); j++) {
      
      int idx = 0;
      for (int ch = 0; ch < MUX_CHANNELS; ch++) {
        setMuxChannel(ch);
        delayMicroseconds(5); // tiny settling time for the mux

        // read all 4 ADS channels
        int16_t a0 = ads.readADC_SingleEnded(0);
        int16_t a1 = ads.readADC_SingleEnded(1);
        int16_t a2 = ads.readADC_SingleEnded(2);
        int16_t a3 = ads.readADC_SingleEnded(3);

        readings[idx++][j+(i*5)] = a0 * (LSB_MV / 1000.0F); // volts
        readings[idx++][j+(i*5)] = a1 * (LSB_MV / 1000.0F);
        readings[idx++][j+(i*5)] = a2 * (LSB_MV / 1000.0F);
        readings[idx++][j+(i*5)] = a3 * (LSB_MV / 1000.0F);
      }

      // 2) Print a single line: <x_position_mm> <y_position_mm> <v1> <v2> ... <v64>
      // float x_pos_mm = stepsToMm(x_currentSteps);
      // float y_pos_mm = stepsToMm(y_currentSteps);
      // print position with 3 decimals (e.g., 0.000)
      // Serial.print(x_pos_mm, 3);
      // Serial.print(' ');
      // Serial.print(y_pos_mm, 3);
      // Serial.print(' ');

      // move X axis 2mm here
      moveSteps(mmToSteps(TARGET_RESO), AWAY_DIR, true);

    }

    // move Y axis 2mm here
    moveSteps(mmToSteps(TARGET_RESO), AWAY_DIR, false);

  }

  for (int i = 0; i < MUX_CHANNELS*NUM_MUXES; i++) {
    for (int j = 0; j < sq((ORI_RESO/TARGET_RESO) + 1); j++) {
      Serial.print(readings[i][j], 4);
      if ((i+1)*(j+1) < 899) Serial.print(' ');
    } 
  }
  Serial.println();

  doHoming();

  // buffer
  delay(10);
}

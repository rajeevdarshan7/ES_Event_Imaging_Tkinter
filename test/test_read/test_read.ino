// Enable flow control characters
#define XON  0x11
#define XOFF 0x13

bool pausedByPC = false;

// Multiplexer select pins
const int S0 = 2;
const int S1 = 3;
const int S2 = 4;
const int S3 = 5;

int muxChannelCount = 16;
int totalMux = 4; // 4 mux → 64 channels
int totalChannel = totalMux * muxChannelCount;
int mux_en_pin = 6;
int pwm_out_pin = 9;

// Mux outputs connected to these analog pins
const int muxOutputs[4] = {A0, A1, A2, A3};

// Store all 64 readings
float readings[64];

void setup() {
  Serial.begin(115200, SERIAL_8E2); // 8 data bits, EVEN parity, 2 stop bits

  // Setup mux address select pins
  pinMode(S0, OUTPUT);
  pinMode(S1, OUTPUT);
  pinMode(S2, OUTPUT);
  pinMode(S3, OUTPUT);

  pinMode(pwm_out_pin, OUTPUT);

  // IMPORTANT: set mux enable pin as OUTPUT
  pinMode(mux_en_pin, OUTPUT);

  // Start with MUX disabled (assumes active-low EN; change if your chip is active-high)
  digitalWrite(mux_en_pin, LOW);
  digitalWrite(S0, (ch & 0x01) ? HIGH : LOW);
  digitalWrite(S1, (ch & 0x02) ? HIGH : LOW);
  digitalWrite(S2, (ch & 0x04) ? HIGH : LOW);
  digitalWrite(S3, (ch & 0x08) ? HIGH : LOW);
}

void loop() {    // If PC sends XOFF → stop sending
  if (Serial.available()) {
      char c = Serial.read();
      if (c == XOFF) pausedByPC = true;
      if (c == XON)  pausedByPC = false;
  }

  if (pausedByPC) {
    delay(1);  // tiny idle delay to avoid 100% CPU spin
    return;
  }

  int idx = 0;

  // Iterate through all mux channels
  for (int ch = 0; ch < muxChannelCount; ch++) {
    // Disable while changing address to avoid glitches
    digitalWrite(mux_en_pin, HIGH);   // disable (if EN is active-low)
    delayMicroseconds(5);

    setMuxChannel(ch); // Select channel on all muxes
    delayMicroseconds(5); // allow address lines to settle

    // Enable the mux output
    digitalWrite(mux_en_pin, LOW); // enable (if EN is active-low)
    delay(1); // give time to settle for measurement / other devices

    // Read all 4 mux outputs through A0–A3
    for (int m = 0; m < totalMux; m++) {
      int raw = analogRead(muxOutputs[m]);
      readings[idx++] = (raw / 1023.0) * 5.0; // Convert to voltage (0–5V)
    }

    //write to UART

    // Optionally disable again before next channel
    digitalWrite(mux_en_pin, HIGH);
    delayMicroseconds(100);
  }

  // Convert your array → string
  String msg = "";
  for (int i = 0; i < totalChannel; i++) {
      msg += String(readings[i], 3);
      if (i < totalChannel - 1) msg += " ";
  }

  // ---- Compute 1-byte checksum (XOR of bytes) ----
  uint8_t checksum = 0;
  for (int i = 0; i < msg.length(); i++)
      checksum ^= msg[i];

  // ---- Send framed message ----
  Serial.print('<');
  Serial.print(msg);
  Serial.print('|');
  
  char cs_hex[3];              // 2 chars + null terminator
  sprintf(cs_hex, "%02X", checksum);
  Serial.print(cs_hex);

  Serial.print('>');
  
  delayMicroseconds(100);  // small pacing delay
}

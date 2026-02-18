// --- Multiplexer Configuration ---
const int S0 = 2;
const int S1 = 3;
const int S2 = 4;
const int S3 = 5;

const int muxChannelCount = 16;
const int totalMux = 4; // 4 mux × 16 = 64 channels

// Mux outputs connected to these analog pins
const int muxOutputs[4] = {A0, A1, A2, A3};

// Store all 64 readings
float readings[64];

void setup() {
  Serial.begin(115200); 

  // Setup mux address and enable pins
  pinMode(S0, OUTPUT);
  pinMode(S1, OUTPUT);
  pinMode(S2, OUTPUT);
  pinMode(S3, OUTPUT);

  // Optional: set ADC reference to 5V or internal
  analogReference(DEFAULT); // DEFAULT = 5V reference on Mega
}

void setMuxChannel(int ch) {
  // Select one of 16 inputs
  digitalWrite(S0, (ch & 1) ? HIGH : LOW);
  digitalWrite(S1, (ch & 2) ? HIGH : LOW);
  digitalWrite(S2, (ch & 4) ? HIGH : LOW);
  digitalWrite(S3, (ch & 8) ? HIGH : LOW);
}

void loop() {
  int idx = 0;

  for (int ch = 0; ch < muxChannelCount; ch++) {
    setMuxChannel(ch);
    delayMicroseconds(200); // Allow mux & ADC to settle

    // Read all 4 mux outputs through A0–A3
    for (int m = 0; m < 4; m++) {
      int raw = analogRead(muxOutputs[m]);
      readings[idx++] = (raw / 1023.0) * 5.0; // Convert to voltage (0–5V)
    }
  }

  // Print all 64 readings in one line
  for (int i = 0; i < 64; i++) {
    Serial.print(readings[i], 3);
    if (i < 63) Serial.print(' ');
    delayMicroseconds(1000);
  }
  Serial.println();
}

// Multiplexer select pins
const int S0 = 2;
const int S1 = 3;
const int S2 = 4;
const int S3 = 5;

int muxChannelCount = 16;
int totalMux = 4; // 4 mux → 64 channels

int mux_en_pin = 6;

void setup() {
  Serial.begin(115200);

  // Setup mux address select pins
  pinMode(S0, OUTPUT);
  pinMode(S1, OUTPUT);
  pinMode(S2, OUTPUT);
  pinMode(S3, OUTPUT);

  // IMPORTANT: set mux enable pin as OUTPUT
  pinMode(mux_en_pin, OUTPUT);

  // Start with MUX disabled (assumes active-low EN; change if your chip is active-high)
  digitalWrite(mux_en_pin, HIGH);

  Serial.println("Starting multiplexer scan...");
}

void setMuxChannel(int ch) {
  // ch = 0–15
  digitalWrite(S0, (ch & 0x01) ? HIGH : LOW);
  digitalWrite(S1, (ch & 0x02) ? HIGH : LOW);
  digitalWrite(S2, (ch & 0x04) ? HIGH : LOW);
  digitalWrite(S3, (ch & 0x08) ? HIGH : LOW);
}

void loop() {
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

    // do whatever reading/drive you need here...
    // For debug: toggle an LED or read with analogRead and print value

    // Optionally disable again before next channel
    digitalWrite(mux_en_pin, HIGH);
    delayMicroseconds(100);
  }
}

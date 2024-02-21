// global variables
int bitNumber = 10;
double maxAnalogVoltage = 5.01;  // Measured between AVCC (20) and GND (22) on the ATMEGA328P.
int pressureInputPin = A5;
int refillStatusPin = A0;
String deviceName = "Arduino-Uno-R3";

void setup() {
  // open a serial connection
  Serial.begin(9600);
}

double analog_value_to_voltage(int value) {
  // Converts analog read values to equivalent voltage
  return value / pow(2., bitNumber) * maxAnalogVoltage;
}

int is_refilling(int value) {
  // Converts refill analog read to refill status (0 or 1).
  if (value == 0) {
    return 0;
  } else if (value == 1 || value == 2) {
    return 1;
  } else {
    return -1;
  }
}


void loop() {

  if (Serial.available() > 0) {
    String userInput = Serial.readStringUntil("\r\n"); // Read until newline character
    userInput.trim(); // removes end-characters

    if (userInput == "*IDN?") {
      Serial.println(deviceName);
    } else if (userInput == "*CLR") {
    } else if (userInput == "PRESSURE?") {
      int pressureValue = analogRead(pressureInputPin);
      Serial.println(analog_value_to_voltage(pressureValue));
    } else if (userInput == "REFILL?") {
      int refillValue = analogRead(refillStatusPin);
      Serial.println(is_refilling(refillValue));
    } else {
      Serial.println("Error: Invalid input: " + userInput + ". You can only query \"PRESSURE?\" or \"REFILL?\".");
    }
    // Clear buffer to avoid unexpected behavior
    while (Serial.available()) {
      Serial.read();
    }
  }
}

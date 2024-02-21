# Run GUI

To run the all-inclusive GUI, run the file `gui/application.py`.

To run the main cryostat monitor GUI, run the file `gui/windows/cryostat.py`.

To run the main temperature controller GUI, run the file `gui/windows/temperature_controller.py`.

If you get a package import error, run the following line and try to run your code again:
```
$env:PYTHONPATH=$(Get-Item .).FullName
```

# Future Development goals

1. Slack sends status report when requested by user on Slack
2. ~~Auto-reset cold head heater when the power system glitches. Add button.~~
3. ~~Change folder to 35share/magnetlog/data~~, share folder link and plot data online
4. Add 'Adjust to pressure' functionality with the temperature control panel
5. Print caught errors:
   1. with [tracebacks](https://docs.python.org/3/library/traceback.html#traceback.print_stack).
   2. with [colors](https://pypi.org/project/colorama/).
   3. in a [logger](https://docs.python.org/3/library/logging.html).
   4. to a file in an "error" folder via the logger.
6. Add comments and docstrings on gui.
7. Change GUI widgets so that they no longer use validation, just binds to the return press.
8. Refactor gui subpackage with a widget file and a separate utils file.
9. Log and print status reports and other alerts that are communicated.
10. ~~Move sensitive information (email password and slack webhooks) to a file accessed via OS environment calls.~~
11. Arduino
    1. Software
       1. Remove Bootloader from Arduino.
       2. Send only bits using `Serial.write()` and not `Serial.print()` for faster communication. Conversion of values will then happen in the Python end.
       3. Perform at least two `analogRead()`s every time before sending data out.
       4. Flip between digital and analog inputs (between these measurements or 4 measurements total?) to discharge the `analogRead()` capacitor.
    2. Hardware
       1. Find a way to measure pressure from -1 V to 4 V.
          1. A good way to do that is to use a voltage inverter (op amp with amplification x1). More specifically, you can split the signal (same voltage) in two channels. one will go to e.g. A0 and the other through the op amp inversion channel, and then to A1. Then either channel A0 will be non-zero, or A1 will be non-zero.
          2. We can also use a voltage divider logic to give each chanel a smaller range (e.g. 0 V to 4 V instead of 0 V to 5 V).
       2. Use a capacitor to discharge the `analogRead()` measurement capacitor?

# Setting up VScode
To make sure code runs with VScode the same as it runs with PyCharm using a virtual environment:

1. Open the file `.venv/Sricpts/Activate.ps1`.
2. Navigate to the line that reads `# Add the venv to the PATH` (line 245 at the moment of writing, VScode version 1.85.1).
3. We need to add the working directory to the environment variable `PYTHONPATH`, so we insert the lines:
    ```
    # Add working directory to PYTHONPATH
    $env:PYTHONPATH=$(Get-Item .).FullName
    ```
4. Restart the terminal, and you should be good to go!

If you get a package import error, run the following line and try to run your code again:
```
$env:PYTHONPATH=$(Get-Item .).FullName
```

# Setting up Arduino
I am using an Arduino Uno R3 to connect the pressure and the refill BNCs.
In order to properly configure the Arduino it is important to know that:

1. The Bootloader is a program that runs every time the device is reset. For some reason, it resets turns off every time I disconnect the code from the device. This program has a time overhead of 2 seconds. In future implementations I hope to remove that issue, by removing the bootloader.
2. The Arduino measures analog voltage through a capacitor charge-discharge proccess. That means that often times there is cross-talk between channels. I eliminate part of that, but it still needs work.
3. The Arduino measures analog voltage through an Analog-to-Digital-Converter. It uses a reference voltage of ~5 V (can be changed) and the device ground with a total number of 10 bits. That means that the precision with which we can measure voltage within this range is <~0.005 V, Should be good enough for what we are doing.
4. The reference voltage depends on the ATMEGA328P on the Arduino. It must have a good power source. If you power the Arduino via the computer, the reference will fluctuate a lot! To accurately measure the reference voltage, measure the voltage difference between [pin 20 (ACVV) and 22 (GND)](https://docs.Arduino.cc/hacking/hardware/PinMapping168).
5. The Arduino outputs only bytes when you use the function `analogRead()`. As of now, I convert this output for each of our measurement. However, because this depends on measurements, and in the future I want to implement a better way to carry out measruments with a more complicated circuit setup, I will just output the bits and let the user get the numbers they need out of the device using python.
6. When measuring analog input, it is important to ground all analog inputs to the same GND!
7. When measuring analog input, it is also important to ground all floating (not connected) pins to the ground via a large resistance (at the time of writing I am using a 10 KΩ resistance).

I will include all versions of the implemented Arduino sketch code `*.ino` in a folder in this project.

# Setting up slack messaging

Right now, we are sending messages via a webhook. The webhook allows python to directly message a specific channel.
We have two channels, one for production (every day, stable version use) and one for development. Check out the slack website for more information.

# Copyright

Copyright (C) 2024, UW-Quantum-Defect-Lab

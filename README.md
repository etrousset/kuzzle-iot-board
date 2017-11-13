# rpi-kuzzle-multi-sensor

The multi sensor device based on a raspberry pi to demonstratre Kuzzle usage as IoT backend

## Sensors

### Light sensor Tept5700

Light level is measured using TEPT5700 ambiant light sensor, datasheet is available here: file:///home/etrousset/Documents/Datasheet/TEPT5700.pdf
The light level acquisition is done using a 12bits DAC (MCP3208) through SPI bus

### NFC

An PN532 NFC/RFID module is used to read RFID cards, connected to UART '/dev/serial0'

### Buttons

4 buttons are connected to GPIOS [6, 13, 19, 26]

### Motion sensor

A motion sensor is connected to GPIO 5



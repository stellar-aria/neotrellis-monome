import board
import busio
import time
import digitalio

from adafruit_neotrellis.multitrellis import MultiTrellis
from adafruit_neotrellis.neotrellis import NeoTrellis
from monome_serial_device import MonomeSerialDevice
from usb_cdc import Serial

brightness: float = 1.0
R = 255
G = 255
B = 255

gamma_table = [0, 2, 3, 6, 11, 18, 25, 32, 41, 59, 70, 80, 92, 103, 115, 128]

is_inited = False
device_id = "neo-monome"
serial_num = "m4216124"

mfgstr = "monome"
prodstr = "monome"
serialstr = "m4216124"

# Monome class setup
mdp: MonomeSerialDevice

prev_led_buffer = []

# create the i2c object for the trellis
i2c = busio.I2C(board.GP27, board.GP26)

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

trellis_array = [
    [
        NeoTrellis(i2c, False, addr=0x30),
        NeoTrellis(i2c, False, addr=0x31),
        NeoTrellis(i2c, False, addr=0x32),
        NeoTrellis(i2c, False, addr=0x33),
    ],
    [
        NeoTrellis(i2c, False, addr=0x36),
        NeoTrellis(i2c, False, addr=0x2E),
        NeoTrellis(i2c, False, addr=0x2F),
        NeoTrellis(i2c, False, addr=0x3E),
    ],
]

trellis = MultiTrellis(trellis_array)
num_rows = int(trellis._rows * 4)
num_cols = int(trellis._cols * 4)
num_leds = num_rows * num_cols

# Helpers


# Input a value 0 to 255 to get a color value.
# The colors are a transition r - g - b - back to r.
def wheel(pos):
    if pos < 85:
        r = int(pos * 3)
        g = int(255 - pos * 3)
        b = 0
    elif pos < 170:
        pos -= 85
        r = int(255 - pos * 3)
        g = 0
        b = int(pos * 3)
    else:
        pos -= 170
        r = 0
        g = int(pos * 3)
        b = int(255 - pos * 3)
    return (r, g, b)


# Functions for Trellis


def key_callback(x, y, edge):
    if edge == NeoTrellis.EDGE_RISING:
        mdp.send_grid_key(x, y, True)
    elif edge == NeoTrellis.EDGE_FALLING:
        mdp.send_grid_key(x, y, False)


# SEND LEDS
def send_leds():
    value = prev_value = 0

    for y in range(num_rows):
        for x in range(num_cols):
            value = mdp.leds[y][x]
            prev_value = prev_led_buffer[y][x]
            gvalue = gamma_table[value]

            if value != prev_value:
                color = (
                    (gvalue * R) // 256,
                    (gvalue * G) // 256,
                    (gvalue * B) // 256,
                )
                trellis.color(x, y, color)
                prev_led_buffer[y][x] = value


def startup_animation():
    trellis.color(0, 0, 0xFFFFFF)
    time.sleep(0.1)
    trellis.color(0, 0, 0x000000)


# Setup
while not Serial.connected:
    time.sleep(0.5)

mdp = MonomeSerialDevice.as_grid(num_rows, num_cols)
mdp.device_id = device_id
monome_refresh = time.monotonic()
is_inited = True

for x in range(8):
    mdp.poll()
    time.sleep(0.1)

# key callback
for x in range(num_cols):
    for y in range(num_rows):
        trellis.activate_key(x, y, NeoTrellis.EDGE_RISING, True)
        trellis.activate_key(x, y, NeoTrellis.EDGE_FALLING, True)
        trellis.set_callback(x, y, key_callback)

# set overall brightness for all pixels
for x in range(num_cols // 4):
    for y in range(num_rows // 4):
        trellis_array[y][x].pixels.brightness = brightness

mdp.set_all_grid_leds(0)
send_leds()
startup_animation()


# Loop
while True:
    mdp.poll()  # process incoming serial from Monomes

    # refresh every 16ms or so
    if is_inited and int(time.monotonic() - monome_refresh) > 16:
        trellis.sync()
        send_leds()
        time.sleep(0.02)

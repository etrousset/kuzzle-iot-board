import json

import asyncio

import sys

from neopixel import *
import time
from kuzzle.kuzzle import KuzzleIOT
from enum import Enum, unique
import logging
import coloredlogs
import asyncio

# LED strip configuration:
LED_COUNT = 8  # Number of LED pixels.
# LED_PIN        = 18      # GPIO pin connected to the pixels (18 uses PWM!).
LED_PIN = 21  # GPIO pin connected to the pixels (21 uses PCM).
# LED_PIN        = 10      # GPIO pin connected to the pixels (10 uses SPI /dev/spidev0.0).
LED_FREQ_HZ = 800000  # LED signal frequency in hertz (usually 800khz)
LED_DMA = 5  # DMA channel to use for generating signal (try 5)
LED_BRIGHTNESS = 255  # Set to 0 for darkest and 255 for brightest
LED_INVERT = False  # True to invert the signal (when using NPN transistor level shift)
LED_CHANNEL = 0  # set to '1' for GPIOs 13, 19, 41, 45 or 53
LED_STRIP = ws.WS2811_STRIP_GRB  # Strip type and colour ordering


@unique
class LightMode(Enum):
    SINGLE_COLOR = "single-color"
    COLOR_RAMP = "color-ramp"


class NeopixelDevice(Adafruit_NeoPixel):

    LOG = logging.getLogger('Neopixel')

    def __init__(self, led_count, led_pin, freq_hz=800000, dma_channel=5, invert=False,
                 brightness=255, pwm_channel=0, strip_type=ws.WS2811_STRIP_RGB):
        super().__init__(led_count, led_pin, freq_hz=freq_hz, dma=dma_channel, invert=invert, brightness=brightness,
                         channel=pwm_channel, strip_type=strip_type)

        coloredlogs.install(logger=NeopixelDevice.LOG,
                            fmt='[%(thread)d] - %(asctime)s - %(name)s - %(levelname)s - %(message)s',
                            level=logging.DEBUG,
                            stream=sys.stdout)

        self.LOG.setLevel(logging.DEBUG)

        self.LOG.info("Neopixel inside")

        self.event_loop = asyncio.get_event_loop()
        self.k = None
        self.led_count = led_count
        self.__state = {
            'on': True,
            'mode': LightMode.COLOR_RAMP.value,
            'ramp': [(255, 0, 0) for x in range(0, LED_COUNT)]
        }
        self.begin()

    def __apply_state(self):

        self.LOG.debug("Applying new state: %s", json.dumps(self.state, sort_keys=True))
        mode = self.state["mode"]

        if self.state['on']:
            if mode == LightMode.SINGLE_COLOR.value:
                color = self.state["color"]

                if type(color) == str:
                    if str(color).startswith('#'):
                        color = color[1:]
                    color = int(color, 16)

                print("led count", self.led_count, ', color: ', hex(color))

                for i in range(0, self.led_count + 1):
                    self.setPixelColor(i, color)
                    # TODO: Handle the case were color is an int or an (r, g, b) tuple
            elif mode == LightMode.COLOR_RAMP.value:
                for i, c in enumerate(self.state["ramp"]):
                    # print("{:3d}: {}".format(i, c))
                    self.setPixelColorRGB(i, c[0], c[1], c[2])
        else:
            for i in range(0, self.led_count + 1):
                self.setPixelColor(i, 0)

        self.show()

    @property
    def state(self):
        return self.__state

    @state.setter
    def state(self, state: dict):
        self.__state.update(state)
        self.__apply_state()

    def publish_state(self):
        if self.k:
            self.k.publish_state(self.state)

    async def __on_new_state_task(self, state, is_partial):
        self.LOG.debug("__on_new_state_task")
        self.state = state
        self.publish_state()

    def on_new_state(self, state, is_partial):
        self.LOG.debug("on_new_state")
        self.event_loop.create_task(self.__on_new_state_task(state, is_partial))

    def on_kuzzle_connected(self, k):
        self.k = k
        self.k.publish_state(self.state)
        self.k.subscribe_state(self.on_new_state)


if __name__ == '__main__':
    neo = NeopixelDevice(LED_COUNT, LED_PIN, strip_type=ws.WS2811_STRIP_GRB)

    kuzzle_neo = KuzzleIOT('rgb_light_00000000c9591b74', 'Neopixel_8-linear', "192.168.0.17")

    # @formatter: off
    default_state = {
        "on": True,
        "mode": LightMode.COLOR_RAMP.value,
        "ramp": [
            (255, 0, 0),
            (127, 127, 0),
            (0, 255, 0),
            (0, 127, 127),
            (0, 0, 255),
            (127, 0, 127),
            (255, 127, 0),
            (255, 255, 255),
        ]
    }

    # @formatter:on

    neo.state = default_state

    t = kuzzle_neo.connect(neo.on_kuzzle_connected)
    asyncio.get_event_loop().run_until_complete(asyncio.gather(t))
    print("At this point should be connected")
    asyncio.get_event_loop().run_forever()

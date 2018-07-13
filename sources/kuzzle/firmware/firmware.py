#!/usr/bin/python3


import signal
import RPi.GPIO as GPIO
import logging
import coloredlogs
import sys

sys.path.append("..")

import argparse
import ruamel.yaml as YAML
import time
import threading
import asyncio
from neopixeldevice import NeopixelDevice, LED_PIN, LightMode, ws as ws_
from utils import *
from pn532 import Pn532
from kuzzle.kuzzle import KuzzleIOT
import namedtupled

yaml = YAML.YAML()
CONFIG_PATH = '../config'
log = logging.getLogger('MAIN')

UID = None
devices = {}
pn532 = None
neo = None

# @formatter: off
default_state = {
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

GPIO.setmode(GPIO.BCM)

buttons = {
    "button_0": "RELEASED",
    "button_1": "RELEASED",
    "button_2": "RELEASED",
    "button_3": "RELEASED",
}


def init_hw_components(fw_config, hw_config):
    global devices
    global pn532
    global pi
    global UID
    global neo

    kuzzle_cfg = fw_config.kuzzle

    dev_conn = ()  # devices to connect

    UID = rpi_get_serial()
    log.info('Getting device base UID: %s', UID)
    log.info('Connecting to Kuzzle on {}:{}'.format(kuzzle_cfg.host, kuzzle_cfg.port))

    log.debug("Neopixel: led_count = {}".format(hw_config.rgb_light.led_count))
    neo = NeopixelDevice(hw_config.rgb_light.led_count, LED_PIN, strip_type=ws_.WS2811_STRIP_GRB)
    devices["kuzzle_neo"] = KuzzleIOT(
        'rgb_light_{}'.format(UID),
        'neopixel-linear',
        host=kuzzle_cfg.host,
        port=kuzzle_cfg.port,
        owner=fw_config.device.owner,
        additional_info={'led_count': hw_config.rgb_light.led_count}
    )
    dev_conn += (devices["kuzzle_neo"].connect(neo.on_kuzzle_connected),)

    devices["kuzzle_rfid"] = KuzzleIOT(
        "NFC_" + UID,
        "RFID_reader",
        host=kuzzle_cfg.host,
        port=kuzzle_cfg.port,
        owner=fw_config.device.owner
    )
    dev_conn += (devices["kuzzle_rfid"].connect(None),)

    if hw_config.motion_sensor.enabled:
        devices["kuzzle_motion"] = KuzzleIOT(
            "motion_" + UID,
            "motion-sensor",
            host=kuzzle_cfg.host,
            port=kuzzle_cfg.port,
            owner=fw_config.device.owner
        )
        dev_conn += (devices["kuzzle_motion"].connect(None),)

    if hw_config.buttons.enabled:
        devices["kuzzle_buttons"] = KuzzleIOT(
            "buttons_{}".format(UID),
            "button",
            host=kuzzle_cfg.host,
            port=kuzzle_cfg.port,
            owner=fw_config.device.owner
        )
        dev_conn += (devices["kuzzle_buttons"].connect(None),)

    devices["kuzzle_light"] = KuzzleIOT(
        "light_lvl_{}".format(UID),
        "light_sensor",
        host=kuzzle_cfg.host,
        port=kuzzle_cfg.port,
        owner=fw_config.device.owner
    )
    dev_conn += (devices["kuzzle_light"].connect(None),)

    asyncio.get_event_loop().run_until_complete(
        asyncio.gather(*dev_conn)
    )

    attached_devices = []
    for d in devices:
        attached_devices.append(devices[d].device_uid)

    board = KuzzleIOT(
        UID,
        hw_config.type,
        host=kuzzle_cfg.host,
        port=kuzzle_cfg.port,
        owner=fw_config.device.owner,
        additional_info={
            "devices": attached_devices,
            "hw_version": hw_config.hw_version,
            "sw_version": fw_config.firmware.version
        }
    )

    asyncio.get_event_loop().run_until_complete(
        asyncio.gather(
            board.connect(None),
        )
    )

    log.debug('All KuzzleIoT instances are connected...')

    neo.state = default_state
    neo.publish_state()
    pn532 = Pn532('/dev/serial0', devices["kuzzle_rfid"].publish_state)


def logs_init():
    coloredlogs.install(logger=log,
                        fmt='[%(thread)X] - %(asctime)s - %(name)s - %(levelname)s - %(message)s',
                        level=logging.DEBUG,
                        stream=sys.stdout)


class GpioHandler:
    def __init__(self, hw_config):
        self.hw_config = hw_config

    def on_gpio_changed(self, gpio, level):
        if gpio in self.hw_config.buttons.gpios:
            buttons[
                'button_{}'.format(self.hw_config.buttons.gpios.index(gpio))] = 'PRESSED' if not level else 'RELEASED'
            log.debug('Buttons state: %s', buttons)
            devices["kuzzle_buttons"].publish_state(buttons)
        elif gpio == self.hw_config.motion_sensor.gpio:
            log.debug('Motion: %s', 'True' if level else 'False')
            devices["kuzzle_motion"].publish_state({'motion': True if level else False})
        else:
            log.warning('Unexpected GPIO: %d', gpio)

    def on_gpio_changed_up(self, channel):
        time.sleep(0.03)  # 30 ms sleep to make sure the GPIO state is stabilized before reading it
        self.on_gpio_changed(channel, GPIO.input(channel))

    def motion_sensor_install(self):
        GPIO.setup(self.hw_config.motion_sensor.gpio, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(self.hw_config.motion_sensor.gpio, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.add_event_detect(self.hw_config.motion_sensor.gpio, GPIO.BOTH, callback=self.on_gpio_changed_up)

    def buttons_install(self):
        GPIO.setup(self.hw_config.buttons.gpios, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        for gpio in self.hw_config.buttons.gpios:
            GPIO.add_event_detect(gpio, GPIO.BOTH, callback=self.on_gpio_changed_up, bouncetime=50)


def cleanup(hw_config):
    if hw_config.connection_led.enabled:
        GPIO.output(hw_config.connection_led.gpio, 0)

    if hw_config.power_led.enabled:
        GPIO.output(hw_config.power_led.gpio, 0)

    global neo
    neo.state = {
        'on': False,
    }

    GPIO.cleanup()


def start_sensing_light(hw_config):
    log.info("Starting light level sensing thread: reading in MCP channel {}".format(hw_config.light_sensor.mcp_channel))
    import tept5700

    tept = tept5700.Tept5700(5.2, 10000, mcp_channel=hw_config.light_sensor.mcp_channel)
    try:
        while 1:
            voltage, lux = tept.read_lux()
            devices["kuzzle_light"].publish_state({"level": lux})  # "{:.3f}".format(lux)})
            time.sleep(1)
    except KeyboardInterrupt as e:
        pass


class SignalHandler:
    def __init__(self, hw_config):
        self.hw_config = hw_config

    def on_sigterm(self, sig_num, stack_frame):
        log.debug("I'm dying!!!")
        GPIO.output(self.hw_config.connection_led.gpio, 0)
        time.sleep(0.5)
        GPIO.output(self.hw_config.connection_led.gpio, 1)
        time.sleep(0.5)
        GPIO.output(self.hw_config.connection_led.gpio, 0)
        time.sleep(0.5)
        GPIO.output(self.hw_config.connection_led.gpio, 1)
        time.sleep(0.5)
        GPIO.output(self.hw_config.connection_led.gpio, 0)

        log.info("service stopped")
        cleanup(self.hw_config)
        exit(0)


def startup():
    logs_init()

    fw_config, hw_config = load_configs(CONFIG_PATH)
    fw_config = namedtupled.map(fw_config)
    hw_config = namedtupled.map(hw_config)
    kuzzle_config = fw_config.kuzzle

    sh = SignalHandler(hw_config)
    signal.signal(signal.SIGTERM, sh.on_sigterm)

    gpio_handler = GpioHandler(hw_config)


    if hw_config.power_led.enabled:
        GPIO.setup(hw_config.power_led.gpio, GPIO.OUT)
        GPIO.output(hw_config.power_led.gpio, 1)

    if hw_config.connection_led.gpio:
        GPIO.setup(hw_config.connection_led.gpio, GPIO.OUT)
        GPIO.output(hw_config.connection_led.gpio, 0)

    retry = 50
    while retry:
        khost = kuzzle_config.host
        kport = kuzzle_config.port
        res = KuzzleIOT.server_info(khost, kport)

        if res:
            retry = 0
            log.debug('Connected to Kuzzle on http://{}:{}, version = {}'.format(
                khost,
                kport,
                res["serverInfo"]["kuzzle"]["version"])
            )
            init_hw_components(fw_config, hw_config)
            GPIO.output(hw_config.connection_led.gpio, 1)

            if hw_config.motion_sensor.enabled:
                gpio_handler.motion_sensor_install()

            if hw_config.buttons.enabled:
                gpio_handler.buttons_install()

            pn532_thread = threading.Thread(target=pn532.start_polling, name="pn532_polling")
            pn532_thread.daemon = True
            pn532_thread.start()

            light_sensor_thread = threading.Thread(target=start_sensing_light, args=(hw_config,),
                                                   name="light_sensor")
            light_sensor_thread.daemon = True
            light_sensor_thread.start()
        else:
            log.warning("Unable to connect to Kuzzle...")
            retry -= 1
            if retry:
                log.info('Trying to reconnect in 5s, %d retries remaining', retry)
            else:
                log.critical('Impossible to connect to Kuzzle service...quitting')
                exit(-1)

            time.sleep(5)

    try:
        log.info("Entering event loop...")
        asyncio.get_event_loop().run_forever()
        log.info("Configuration changed, restarting firmware...")
    except KeyboardInterrupt as e:
        pass
    finally:
        cleanup(hw_config)


if __name__ == '__main__':
    startup()

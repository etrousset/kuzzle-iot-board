#!/usr/bin/python3

import pigpio
import logging
import coloredlogs
import sys
import argparse
import ruamel.yaml as YAML
import time
import threading

from rpi_get_serial import *
from pn532 import Pn532
from kuzzle.kuzzle import KuzzleIOT

yaml = YAML.YAML()

GPIO_MOTION_SENSOR = 5
GPIO_BUTTONS = [6, 13, 19, 26]
GPIO_LED_GREEN = 21

log = logging.getLogger('MAIN')

UID = None
kuzzle_rfid = None
kuzzle_motion = None
kuzzle_buttons = None
kuzzle_light = None
pn532 = None
pi = None

buttons = {
    "button_0": "RELEASED",
    "button_1": "RELEASED",
    "button_2": "RELEASED",
    "button_3": "RELEASED",
}


def init(args, config):
    global kuzzle_motion
    global kuzzle_buttons
    global kuzzle_rfid
    global kuzzle_light
    global pn532
    global pi
    global UID

    kuzzle_conf = config["kuzzle"]

    UID = rpi_get_serial()
    log.info('Getting device base UID: %s', UID)

    log.info('Connecting to Kuzzle on {}:{}'.format(kuzzle_conf['host'], kuzzle_conf['port']))
    kuzzle_rfid = KuzzleIOT("NFC_" + UID, "RFID_reader", host=kuzzle_conf['host'], port=kuzzle_conf['port'])
    kuzzle_motion = KuzzleIOT("motion_" + UID, "motion-sensor", host=kuzzle_conf['host'], port=kuzzle_conf['port'])
    kuzzle_buttons = KuzzleIOT("buttons_{}".format(UID), "button", host=kuzzle_conf['host'], port=kuzzle_conf['port'])
    kuzzle_light = KuzzleIOT("light_lvl_{}".format(UID), "light_sensor", host=kuzzle_conf['host'],
                             port=kuzzle_conf['port'])

    log.info('Connecting to RPi through: %s', args.pihost)
    pi = pigpio.pi(host=args.pihost)

    if not pi:
        log.critical("Failed to connect to 'pigpiod': %s", args.pihost)
        exit(-1)

    pi.set_mode(GPIO_LED_GREEN, pigpio.OUTPUT)
    pi.write(GPIO_LED_GREEN, 0)

    serial_handle = pi.serial_open('/dev/serial0', 115200)
    if not serial_handle:
        time.sleep(1)
        serial_handle = pi.serial_open('/dev/serial0', 115200)
        if not serial_handle:
            log.critical("Unable to open serial port '/dev/serial0'")
            exit(-1)

    pn532 = Pn532(pi, serial_handle, kuzzle_rfid.publish_state)


def logs_init():
    coloredlogs.install(logger=log, fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.DEBUG,
                        stream=sys.stdout)


def on_gpio_changed(gpio, level, tick):
    if gpio in GPIO_BUTTONS:
        buttons['button_{}'.format(GPIO_BUTTONS.index(gpio))] = 'PRESSED' if level else 'RELEASED'
        log.debug('Buttons state: %s', buttons)
        kuzzle_buttons.publish_state(buttons)
    elif gpio == GPIO_MOTION_SENSOR:
        log.debug('Motion: %s', 'True' if level else 'False')
        kuzzle_motion.publish_state({'motion': True if level else False})
    else:
        log.warning('Unexpected GPIO: %d', gpio)


def motion_sensor_install():
    pi.set_mode(GPIO_MOTION_SENSOR, pigpio.INPUT)
    pi.callback(GPIO_MOTION_SENSOR, pigpio.EITHER_EDGE, on_gpio_changed)


def buttons_install():
    for gpio in GPIO_BUTTONS:
        pi.set_mode(gpio, pigpio.INPUT)
        pi.set_pull_up_down(gpio, pigpio.PUD_UP)
        pi.set_noise_filter(gpio, 30000, 300)
        pi.callback(gpio, pigpio.EITHER_EDGE, on_gpio_changed)


def load_config():
    with open('config.yaml') as f:
        content = f.read()
    return yaml.load(content)


def cleanup():
    if pi and pn532 and pn532.serial_handle:
        pi.serial_close(pn532.serial_handle)
    if pi:
        pi.write(GPIO_LED_GREEN, 0)


def start_sensing_light():
    log.info("Starting light level sensing thread")
    import tept5700

    tept = tept5700.Tept5700(5.2, 10000)
    try:
        while 1:
            voltage, lux = tept.read_lux()
            kuzzle_light.publish_state({"level": "{:.3f}".format(lux)})
            time.sleep(1)
    except KeyboardInterrupt as e:
        pass


def startup(args):
    logs_init()

    config_update_event = args['update_evt']
    cmd_args = args['cmd_line']

    config = load_config()
    init(cmd_args, config)

    res = kuzzle_motion.server_info()

    if res:
        log.debug('Connected to Kuzzle on http://{}:{}, version = {}'.format(
            kuzzle_motion.host,
            kuzzle_motion.port,
            res["serverInfo"]["kuzzle"]["version"])
        )
        pi.write(GPIO_LED_GREEN, 1)
        motion_sensor_install()
        buttons_install()
        if pn532.version_check():
            log.info('Found a Pn532 RFID/NFC module, starting card polling...')
            pn532_thread = threading.Thread(target=pn532.start_polling, name="pn532_polling")
            pn532_thread.daemon = True
            pn532_thread.start()

        light_sensor_thread = threading.Thread(target=start_sensing_light, name="light_sensor")
        light_sensor_thread.daemon = True
        light_sensor_thread.start()
    else:
        log.warning("Unable to connect to Kuzzle...")

    config_update_event.wait()
    log.info("Configuration changed, restarting firmware...")
    config_update_event.clear()

    cleanup()

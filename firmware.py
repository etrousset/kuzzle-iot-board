#!/usr/bin/python3

import RPi.GPIO as GPIO
import serial
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
GPIO_NFC_IRQ = 20

log = logging.getLogger('MAIN')

UID = None
kuzzle_rfid = None
kuzzle_motion = None
kuzzle_buttons = None
kuzzle_light = None
pn532 = None

GPIO.setmode(GPIO.BCM)

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

    GPIO.setup(GPIO_LED_GREEN, GPIO.OUT)
    GPIO.output(GPIO_LED_GREEN, 0)

    serial_port = serial.Serial('/dev/serial0', 115200)

    log.info('Serial port is: %s', 'OPENED' if serial_port.is_open else 'CLOSED')
    pn532 = Pn532(serial_port, kuzzle_rfid.publish_state)


def logs_init():
    coloredlogs.install(logger=log, fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.DEBUG,
                        stream=sys.stdout)


def on_gpio_changed(gpio, level):
    if gpio in GPIO_BUTTONS:
        buttons['button_{}'.format(GPIO_BUTTONS.index(gpio))] = 'PRESSED' if not level else 'RELEASED'
        log.debug('Buttons state: %s', buttons)
        kuzzle_buttons.publish_state(buttons)
    elif gpio == GPIO_MOTION_SENSOR:
        log.debug('Motion: %s', 'True' if level else 'False')
        kuzzle_motion.publish_state({'motion': True if level else False})
    else:
        log.warning('Unexpected GPIO: %d', gpio)


def on_gpio_changed_up(channel):
    on_gpio_changed(channel, GPIO.input(channel))


def on_gpio_changed_down(channel):
    on_gpio_changed(channel, 0)


def motion_sensor_install():
    GPIO.setup(GPIO_MOTION_SENSOR, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.add_event_detect(GPIO_MOTION_SENSOR, GPIO.BOTH, callback=on_gpio_changed_up)


def buttons_install():
    GPIO.setup(GPIO_BUTTONS, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    for gpio in GPIO_BUTTONS:
        GPIO.add_event_detect(gpio, GPIO.BOTH, callback=on_gpio_changed_up, bouncetime=200)


def load_config():
    with open('config.yaml') as f:
        content = f.read()
    return yaml.load(content)


def cleanup():
    GPIO.output(GPIO_LED_GREEN, 0)
    GPIO.cleanup()


def start_sensing_light():
    log.info("Starting light level sensing thread")
    import tept5700

    tept = tept5700.Tept5700(5.2, 10000)
    try:
        while 1:
            voltage, lux = tept.read_lux()
            kuzzle_light.publish_state({"level": lux})  # "{:.3f}".format(lux)})
            time.sleep(0.1)
    except KeyboardInterrupt as e:
        pass


def startup(args):
    logs_init()

    config_update_event = args['update_evt']
    cmd_args = args['cmd_line']

    config = load_config()
    init(cmd_args, config)

    retry = 3
    while retry:
        res = kuzzle_motion.server_info()

        if res:
            retry = 0
            log.debug('Connected to Kuzzle on http://{}:{}, version = {}'.format(
                kuzzle_motion.host,
                kuzzle_motion.port,
                res["serverInfo"]["kuzzle"]["version"])
            )
            GPIO.output(GPIO_LED_GREEN, 1)
            motion_sensor_install()
            buttons_install()
            while 1:
                if pn532.version_check():
                    log.info('Found a Pn532 RFID/NFC module, starting card polling...')
                    pn532_thread = threading.Thread(target=pn532.start_polling, name="pn532_polling")
                    pn532_thread.daemon = True
                    pn532_thread.start()
                    break
                else:
                    log.warning('Unable to get version from Pn532, not using it...')
                    time.sleep(1)

            light_sensor_thread = threading.Thread(target=start_sensing_light, name="light_sensor")
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
        config_update_event.wait()
        log.info("Configuration changed, restarting firmware...")
        config_update_event.clear()
    except KeyboardInterrupt as e:
        pass
    finally:
        cleanup()

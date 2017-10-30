#!/usr/bin/python3

import pigpio
import logging
import coloredlogs
import sys
import argparse

from rpi_get_serial import *
from pn532 import Pn532
from kuzzle.kuzzle import KuzzleIOT

GPIO_MOTION_SENSOR = 5
GPIO_BUTTONS = [6, 13, 19, 26]

UID = rpi_get_serial()
log = logging.getLogger('MAIN')

kuzzle_rfid = None
kuzzle_motion = None
kuzzle_buttons = None
pn532 = None
pi = None


def init(args):
    global kuzzle_motion
    global kuzzle_buttons
    global kuzzle_rfid
    global pn532
    global pi

    kuzzle_rfid = KuzzleIOT("NFC_" + UID, "RFID_reader", args.khost, user=args.kuser, pwd=args.kpwd)
    kuzzle_motion = KuzzleIOT("motion_" + UID, "motion-sensor", args.khost, user=args.kuser, pwd=args.kpwd)
    kuzzle_buttons = KuzzleIOT("buttons_{}".format(UID), "button", args.khost, user=args.kuser, pwd=args.kpwd)

    pi = pigpio.pi(host=args.pihost)

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
        log.debug('Button %d is %s', GPIO_BUTTONS.index(gpio), 'PRESSED' if level else 'RELEASED')
        kuzzle_buttons.publish_state({'button_{}'.format(GPIO_BUTTONS.index(gpio)): 'PRESSED' if level else 'RELEASED'})
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
        pi.set_noise_filter(gpio, 50000, 300
        pi.callback(gpio, pigpio.EITHER_EDGE, on_gpio_changed)

if __name__ == "__main__:
    parser = argparse.ArgumentParser(description='Kuzzle multi sensor demo')

    parser.add_argument('--pihost', default='localhost',
                        help='The host pi to witch the pigpio will connect if user in remote')
    parser.add_argument('--khost', required=True, help='Kuzzle host')
    parser.add_argument('--kport', default=7512, type=int, help='Kuzzle port, default is 7512')
    parser.add_argument('--kuser', help='Kuzzle port, default is 7512')
    parser.add_argument('--kpwd', help='Kuzzle port, default is 7512')

    a = parser.parse_args(sys.argv[1:])
    print(a)
    logs_init()
    init(a)

    motion_sensor_install()
    buttons_install()
    pn532.version_check()
    pn532.start_polling()

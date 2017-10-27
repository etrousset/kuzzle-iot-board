#!/usr/bin/python3

import pigpio
import logging
import coloredlogs
import time

import sys

from rpi_get_serial import *
from kuzzle.kuzzle import KuzzleIOT

UID = rpi_get_serial()

kuzzle = KuzzleIOT("NFC_" + UID, "RFID_reader", "192.168.1.108", user="etrousset", pwd="rootroot")

pi = pigpio.pi(host="kuzzle-sensor.local")

log = logging.getLogger('MAIN')

PN532_ACK = bytes([0x00, 0x00, 0xFF, 0x00, 0xFF, 0x00])

PN532_DIAGNOSE_FRAME = 0x01
PN532_GET_FIRMWARE_VERSION_FRAME = 0x02

rfid_h = pi.serial_open('/dev/serial0', 115200)


def hex_dump(b, sep=' '):
    _str = ""
    for a in b:
        _str += "%02X" % a
        _str += sep

    return _str


def pn532_frame(cmd: int, data: bytes = None) -> bytes:
    frame = bytes([0x00, 0x00, 0xFF, ])

    l = 2 if not data else len(data) + 2
    lcs = (-l) & 0xFF
    frame += bytes([l, lcs, 0xD4, cmd])
    if data:
        frame += data

    s = (0xD4 + cmd + (sum(data) if data else 0)) & 0xFF
    dcs = (-s) & 0xFF
    frame += bytes([dcs, 0x00])

    return frame


def pn532_check_ack(frame: bytes) -> bool:
    return frame == PN532_ACK


def pn532_parse_firmware_version(frame):
    if bytes(frame[:6]) == b"\x00\x00\xff\x06\xfa\xd5":
        IC = frame[7]
        ver = frame[8]
        rev = frame[9]
        support = frame[10]
        return {'IC': IC, 'Ver': ver, 'Rev': rev, 'Support': support}
    else:
        log.critical("Invalide firmware version frame: %s", frame)
        return None


def pn532_parse_card_id(frame):
    data = frame[7:]
    nb_cards = data[0]
    card_type = data[1]
    card_len = data[2]
    card_data = data[3:card_len + 3]
    SENS_RES = card_data[1:3]
    SEL_RES = card_data[3]
    NFCID_len = card_data[4]
    NFCID = card_data[5:5 + NFCID_len]

    if nb_cards != 1:
        log.warning('Not reading second card info...')

    # NFCID = int.from_bytes(NFCID, byteorder='little')
    # SENS_RES = int.from_bytes(SENS_RES, byteorder='little')
    return {'SENS_RES': SENS_RES, 'SEL_RES': SENS_RES, 'NFCID': NFCID}


def pn532_start_polling():
    log.debug("Sending polling cmd for Nfc card...")
    polling_cmd = 0x60
    polling_data = [0xFF, 0x01, 0x10]

    in_list_passive_target_cmd = 0x4A
    in_list_passive_target_data = [0x01, 0x00, ]

    frame = pn532_frame(polling_cmd, bytes(polling_data))
    pi.serial_write(rfid_h, frame)
    time.sleep(1)
    l, frame = pi.serial_read(rfid_h)
    if pn532_check_ack(frame):
        log.debug('InAutoPoll - ACK OK')

    while 1:
        l, frame = pi.serial_read(rfid_h)
        if frame:
            log.debug(hex_dump(frame))
            card = pn532_parse_card_id(frame)

            log.info('In field: card ID: 0x%04x', int.from_bytes(card["NFCID"], byteorder='little'))

            kuzzle.publish_state({'card_id': hex_dump(card["NFCID"], ''), 'in_field': True})

            in_field = True
            while in_field:

                frame = pn532_frame(0x32, bytes([0x05, 0x00, 0x01, 0x02]))
                log.debug('RfConfiguration: %s', hex_dump(frame))
                pi.serial_write(rfid_h, frame)

                time.sleep(0.3)
                l, frame = pi.serial_read(rfid_h, 6)

                if pn532_check_ack(frame):
                    log.debug('RfConfiguration - ACK OK')
                else:
                    log.error('RfConfiguration - ACK NOT OK')

                time.sleep(0.3)
                l, frame = pi.serial_read(rfid_h)
                log.debug(hex_dump(frame))

                frame = pn532_frame(in_list_passive_target_cmd, bytes(in_list_passive_target_data) + card["NFCID"])
                log.debug('InListPassive: %s', hex_dump(frame))
                pi.serial_write(rfid_h, frame)
                time.sleep(0.3)
                l, frame = pi.serial_read(rfid_h, 6)
                if pn532_check_ack(frame):
                    log.debug('InListPassive - ACK OK')
                else:
                    log.debug('InListPassive - ACK NOT OK')

                time.sleep(0.3)
                l, frame = pi.serial_read(rfid_h)
                log.debug(hex_dump(frame))

                in_field_cards_count = frame[7]
                in_field = in_field_cards_count != 0

                if not in_field:
                    kuzzle.publish_state({'card_id': hex_dump(card["NFCID"], ''), 'in_field': False})

                    frame = pn532_frame(polling_cmd, bytes(polling_data))
                    pi.serial_write(rfid_h, frame)
                    time.sleep(0.1)
                    l, frame = pi.serial_read(rfid_h)
                    if pn532_check_ack(frame):
                        log.debug('InAutoPoll - ACK OK')

        time.sleep(1)

    log.debug(frame)


def logs_init():
    coloredlogs.install(logger=log, fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.DEBUG,
                        stream=sys.stdout)


def pn532_init():
    if not rfid_h:
        log.critical("Unable to open serial port '/dev/serial0'")
        exit(-1)

    # check we are able to communicate with PN532

    log.debug("Get PN532 firmware revision: GetFirmwareVersion")
    pi.serial_write(rfid_h, pn532_frame(PN532_GET_FIRMWARE_VERSION_FRAME))
    time.sleep(1)
    l, frame = pi.serial_read(rfid_h, 6)

    if not pn532_check_ack(frame):

        log.error("Didn't get a valid ACK from PN532: %s", hex_dump(frame))
    else:
        log.debug("ACK OK")

    time.sleep(1)
    l, frame = pi.serial_read(rfid_h)

    log.debug('Firmware version recv frame: %s', hex_dump(frame))
    fw_version = pn532_parse_firmware_version(frame)

    if fw_version:
        log.debug('Found PN53 version: %d.%d', fw_version['Ver'], fw_version['Rev'])
    else:
        log.error('Failed to get version from PN532')


logs_init()
pn532_init()
pn532_start_polling()

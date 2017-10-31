import logging
import coloredlogs
import pigpio
import sys

import time


class Pn532(object):
    ACK = bytes([0x00, 0x00, 0xFF, 0x00, 0xFF, 0x00])

    CMD_DIAGNOSE = 0x01
    CMD_GET_FIRMWARE_VERSION = 0x02
    CMD_IN_LIST_PASSIVE_TARGET = 0x4A
    CMD_IN_AUTO_POLL = 0x60
    CMD_RF_CONFIGURATION = 0x32

    LOG = logging.getLogger('PN532')

    def __init__(self, pi: pigpio.pi, serial_handle, state_callback):
        self.pi = pi
        self.serial_handle = serial_handle
        self.state_callback = state_callback

        coloredlogs.install(logger=Pn532.LOG,
                            fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                            level=logging.INFO,
                            stream=sys.stdout)

    def version_check(self):

        # check we are able to communicate with PN532

        self.LOG.debug("Get PN532 firmware revision: GetFirmwareVersion")
        self.pi.serial_write(self.serial_handle, self._frame(Pn532.CMD_GET_FIRMWARE_VERSION))
        time.sleep(0.3)
        l, frame = self.serial_read_ack()

        if not self._check_ack(frame):

            self.LOG.error("Didn't get a valid ACK from PN532: %s", self.hex_dump(frame))
        else:
            self.LOG.debug("ACK OK")

        time.sleep(0.3)
        l, frame = self.serial_read()

        self.LOG.debug('Firmware version recv frame: %s', self.hex_dump(frame))
        fw_version = self.parse_firmware_version(frame)

        if fw_version:
            self.LOG.info('Found PN53 version: %d.%d', fw_version['Ver'], fw_version['Rev'])
        else:
            self.LOG.error('Failed to get version from PN532')
            exit(-1)

    @staticmethod
    def hex_dump(b, sep=' '):
        _str = ""

        for a in b:
            _str += "%02X%s" % (a, sep)

        return _str

    @staticmethod
    def _frame(cmd: int, data: bytes = None) -> bytes:
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

    @staticmethod
    def _check_ack(frame: bytes) -> bool:
        return frame == Pn532.ACK

    @staticmethod
    def parse_firmware_version(frame):
        if bytes(frame[:6]) == b"\x00\x00\xff\x06\xfa\xd5":
            IC = frame[7]
            ver = frame[8]
            rev = frame[9]
            support = frame[10]
            return {'IC': IC, 'Ver': ver, 'Rev': rev, 'Support': support}
        else:
            Pn532.LOG.critical("Invalide firmware version frame: %s", frame)
            return None

    @staticmethod
    def parse_card_id(frame):
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
            Pn532.LOG.warning('Not reading second card info...')

        return {'SENS_RES': SENS_RES, 'SEL_RES': SENS_RES, 'NFCID': NFCID}

    def serial_write(self, frame):
        self.pi.serial_write(self.serial_handle, frame)

    def serial_read(self, count: int = 1000):
        return self.pi.serial_read(self.serial_handle, count)

    def serial_read_ack(self):
        return self.serial_read(6)

    def start_polling(self):
        Pn532.LOG.debug("Sending polling cmd for Nfc card...")

        polling_data = [0xFF, 0x01, 0x10]
        in_list_passive_target_data = [0x01, 0x00, ]

        frame = self._frame(Pn532.CMD_IN_AUTO_POLL, bytes(polling_data))
        self.serial_write(frame)

        time.sleep(1)
        l, frame = self.serial_read_ack()
        if self._check_ack(frame):
            Pn532.LOG.debug('InAutoPoll - ACK OK')
        else:
            Pn532.LOG.warning('InAutoPoll - ACK NOT OK')

        while 1:
            l, frame = self.serial_read()
            if frame:
                Pn532.LOG.debug(self.hex_dump(frame))
                card = self.parse_card_id(frame)

                self.LOG.info('Card ID: 0x%04x entering field', int.from_bytes(card["NFCID"], byteorder='little'))

                self.state_callback({'card_id': self.hex_dump(card["NFCID"], ''), 'in_field': True})

                in_field = True
                while in_field:

                    frame = self._frame(self.CMD_RF_CONFIGURATION, bytes([0x05, 0x00, 0x01, 0x02]))
                    self.LOG.debug('RfConfiguration: %s', self.hex_dump(frame))
                    self.serial_write(frame)

                    time.sleep(0.1)
                    l, frame = self.serial_read_ack()

                    if self._check_ack(frame):
                        self.LOG.debug('RfConfiguration - ACK OK')
                    else:
                        self.LOG.error('RfConfiguration - ACK NOT OK')

                    time.sleep(0.3)
                    l, frame = self.serial_read()
                    self.LOG.debug(self.hex_dump(frame))

                    frame = self._frame(self.CMD_IN_LIST_PASSIVE_TARGET,
                                        bytes(in_list_passive_target_data) + card["NFCID"])
                    self.LOG.debug('InListPassive: %s', self.hex_dump(frame))
                    self.serial_write(frame)
                    time.sleep(0.1)
                    l, frame = self.serial_read_ack()
                    if self._check_ack(frame):
                        self.LOG.debug('InListPassive - ACK OK')
                    else:
                        self.LOG.debug('InListPassive - ACK NOT OK')

                    time.sleep(0.1)
                    l, frame = self.serial_read()
                    self.LOG.debug(self.hex_dump(frame))

                    in_field_cards_count = frame[7]
                    in_field = in_field_cards_count != 0

                    if not in_field:
                        self.state_callback({'card_id': self.hex_dump(card["NFCID"], ''), 'in_field': False})
                        self.LOG.info('Card ID: 0x%04x leaving field', int.from_bytes(card["NFCID"], byteorder='little'))

                        frame = self._frame(self.CMD_IN_AUTO_POLL, bytes(polling_data))
                        self.serial_write(frame)
                        time.sleep(0.1)
                        l, frame = self.serial_read_ack()
                        if self._check_ack(frame):
                            self.LOG.debug('InAutoPoll - ACK OK')
                        else:
                            self.LOG.debug('InAutoPoll - ACK NOT OK')

            time.sleep(1)

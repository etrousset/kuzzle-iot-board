import os
import logging
import coloredlogs
import namedtupled
import ruamel.yaml

yaml = ruamel.yaml.YAML()

log = logging.Logger('RPi')
coloredlogs.install(level=logging.DEBUG, logger=log)


def rpi_get_serial():
    if os.uname()[4] == 'armv7l':
        log.debug('Running on a RPi: Using CPU serial')
        with open('/proc/cpuinfo') as f:
            l = ""
            while not l.startswith('Serial'):
                l = f.readline()

            return l.split(":")[1][1:-1]
    else:
        log.debug('Not running on a RPi: Using alternative serial: %s', "0012345678")
        return "0012345678"


def load_fw_config(path: str) -> dict:
    with open(os.path.join(path, 'config.yaml')) as f:
        content = f.read()
    return yaml.load(content)


def load_hw_config(path: str, config_name: str) -> dict:
    with open(os.path.join(path, 'devices', config_name + ".yaml")) as f:
        content = f.read()
    return yaml.load(content)


def load_configs(path: str) -> (dict, dict):
    fw_config = load_fw_config(path)
    hw_config = load_hw_config(path, fw_config["device"]["hw_config"])
    return fw_config, hw_config

def save_fw_config( path:str, fw_config: dict):
    with open(os.path.join(path, 'config.yaml'), mode='w') as f:
        yaml.dump(fw_config, f)

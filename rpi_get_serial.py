import os


def rpi_get_serial():
    if os.uname()[4] == 'armv7l':
        print('Running on a RPi: Using CPU serial')
        with open('/proc/cpuinfo') as f:
            l = ""
            while not l.startswith('Serial'):
                l = f.readline()

            return l.split(":")[1][1:-1]
    else:
        print('Not running on a RPi: Using alternative serial')
        return "0012345678"

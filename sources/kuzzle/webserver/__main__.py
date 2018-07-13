import utils
from . import *

if __name__ == '__main__':

    CONFIG_PATH = os.path.abspath('config')

    config_update_event = None
    SERVER_ADDRESS = ('', 80)
    # AdminHTTPRequestHandler.protocol_version = 'HTTP/1.1'
    httpd = AdminHTTPServer(
        SERVER_ADDRESS,
        AdminHTTPRequestHandler,
        {'uid': utils.rpi_get_serial()},
        CONFIG_PATH
    )

    httpd.start_admin_server()

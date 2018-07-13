from http.server import *
from http import HTTPStatus
import urllib.parse as uparse
import airspeed
from ruamel.yaml import YAML
import os
import subprocess
import json
import dbus
import glob
import utils
import namedtupled

yaml = YAML()

import sys

def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)
    sys.stdout.flush()


class AdminHTTPServer(HTTPServer):
    def __init__(self, server_address, RequestHandlerClass, device_info, config_path):
        super().__init__(server_address, RequestHandlerClass)
        self.config_path = config_path
        self.device_info = device_info
        self.load_configs()

        self.device_definitions_path = os.path.join(config_path, 'devices')

    def get_device_configs(self) -> list:
        configs = []

        files = glob.glob(self.device_definitions_path + "/*")

        print(files)

        for file in files:
            with open(file) as f:
                dev_desc_str = f.read()
            hw_cfg = yaml.load(dev_desc_str)

            name = os.path.splitext(os.path.basename(file))[0]
            configs.append({"name": name, "desc": hw_cfg["description"]})
        return configs

    def start_admin_server(self):
        server_path = os.path.dirname(__file__)
        os.chdir(server_path)
        self.serve_forever()

    def shutdown_admin_server(self):
        self.shutdown()

    def restart_firmware(self):
        sysbus = dbus.SystemBus()
        systemd1 = sysbus.get_object('org.freedesktop.systemd1', '/org/freedesktop/systemd1')
        manager = dbus.Interface(systemd1, 'org.freedesktop.systemd1.Manager')
        job = manager.RestartUnit('kuzzle-sensor-firmware.service', 'fail')


    def load_configs(self):
        self.fw_config, self.hw_config = utils.load_configs(self.config_path)
        self.device_info["hw_config"] = self.hw_config

    def save_fw_config(self):
        utils.save_fw_config(self.config_path, self.fw_config)

    def apply_kuzzle_config(self, args):
        if 'kport' in args.keys():
            eprint(self.fw_config)
            self.fw_config['kuzzle']["port"] = args['kport']
        if 'khost' in args.keys():
            print(self.fw_config)
            self.fw_config["kuzzle"]["host"] = args['khost']
        self.save_fw_config()
        self.restart_firmware()

    def apply_device_config(self, args):
        if 'hw_config' in args.keys():
            self.fw_config['device']['hw_config'] = args['hw_config']

        if 'owner' in args.keys():
            self.fw_config['device']['owner'] = args['owner']

        self.save_fw_config()
        self.load_configs()
        self.restart_firmware()


class AdminHTTPRequestHandler(SimpleHTTPRequestHandler):

    def do_POST(self):
        if self.path == '/setup':
            content_length = int(self.headers['Content-Length'])
            c = self.rfile.read(content_length)
            args = uparse.parse_qsl(c)
            args = dict([(x[0].decode('utf-8'), x[1].decode('utf-8')) for x in args])
            self.server.apply_kuzzle_config(args)

            self.send_response(301)
            self.send_header("Location", "http://" + self.headers["Host"] + '/admin')
            self.end_headers()

        if self.path == '/config':
            eprint("/config <====================")
            content_length = int(self.headers['Content-Length'])
            c = self.rfile.read(content_length)
            args = uparse.parse_qsl(c)
            args = dict([(x[0].decode('utf-8'), x[1].decode('utf-8')) for x in args])

            print(args)
            self.server.apply_device_config(args)

            self.send_response(301)
            self.send_header("Location", "http://" + self.headers["Host"] + '/admin')
            self.end_headers()

    def do_GET(self):
        if self.path == "/admin":
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-type", "text/html")

            device_configs = self.server.get_device_configs()
            admin_template = self.load_admin_template()
            body = admin_template.merge(
                {
                    'fw_config': namedtupled.reduce(self.server.fw_config),
                    'device': namedtupled.reduce(self.server.device_info),
                    'device_configs': device_configs
                }
            )

            self.send_header("Content-length", len(body))
            self.end_headers()

            self.wfile.write(bytes(body, 'utf-8'))

        elif self.path == "/":
            self.send_response(301)
            self.send_header("Location", "http://" + self.headers["Host"] + '/dashboard')
            self.end_headers()

        elif self.path == "/dashboard":
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-type", "text/html")

            print(namedtupled.reduce(self.server.fw_config))
            print(namedtupled.reduce(self.server.device_info))
            dashboard_template = self.load_dashboard_template()
            body = dashboard_template.merge(
                {
                    'fw_config': namedtupled.reduce(self.server.fw_config),
                    'device': namedtupled.reduce(self.server.device_info),
                }
            )

            self.send_header("Content-length", len(body))
            self.end_headers()

            self.wfile.write(bytes(body, 'utf-8'))
        elif self.path == "/logs":
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-type", "text/plain")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()

            with subprocess.Popen(
                    ['journalctl', '-u', 'kuzzle-sensor-firmware', '-f', '-n', '100'],
                    stdout=subprocess.PIPE,
                    universal_newlines=True
            ) as p:

                try:
                    l = p.stdout.readline()
                    while l:
                        nbchar = '%X' % len(l)
                        self.wfile.write(bytes(nbchar + '\r\n', 'utf-8'))
                        self.wfile.write(bytes(l + '\r\n', 'utf-8'))
                        l = p.stdout.readline()

                    self.wfile.write(bytes('0\r\n', 'utf-8'))
                    self.wfile.write(bytes('\r\n', 'utf-8'))
                except BrokenPipeError as e:
                    print('connection closed by client...')
        elif self.path == "/reboot":
            content = bytes('<html><body><H1>Device rebooting...</H1></HTML></BODY>', 'utf-8')
            l = len(content)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-type", "text/html")
            self.send_header("Content-length", "{}".format(l))
            self.end_headers()
            self.wfile.write(content)

            subprocess.Popen(['reboot'], stdout=subprocess.PIPE, universal_newlines=True)
        else:
            super().do_GET()

    @staticmethod
    def load_admin_template():
        with open('admin.html.vm') as f:
            content = f.read()
        return airspeed.Template(content)

    @staticmethod
    def load_dashboard_template():
        with open('dashboard.html.vm') as f:
            content = f.read()
        return airspeed.Template(content)

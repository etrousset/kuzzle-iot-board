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

yaml = YAML()


class AdminHTTPServer(HTTPServer):
    def __init__(self, server_address, RequestHandlerClass, device_info, config_path):
        super().__init__(server_address, RequestHandlerClass)

        self.config_file = os.path.join(config_path, 'config.yaml')
        self.device_definitions_path = os.path.join(config_path, 'devices')
        self.config = self.load_config()
        self.device_info = device_info

    def get_device_configs(self):
        configs = []

        files = glob.glob(self.device_definitions_path + "/*")

        for file in files:
            with open(file) as f:
                dev_desc_str = f.read()
            desc =  yaml.load(dev_desc_str)

            configs.append({"name": os.path.basename(file), "desc": desc["description"]})
        return configs

    def start_admin_server(self):
        server_path = os.path.dirname(__file__)
        os.chdir(server_path)
        self.serve_forever()

    def shutdown_admin_server(self):
        self.shutdown()

    def load_config(self):
        with open(self.config_file) as f:
            config_str = f.read()
        return yaml.load(config_str)

    def restart_firmware(self):
        sysbus = dbus.SystemBus()
        systemd1 = sysbus.get_object('org.freedesktop.systemd1', '/org/freedesktop/systemd1')
        manager = dbus.Interface(systemd1, 'org.freedesktop.systemd1.Manager')
        job = manager.RestartUnit('kuzzle-sensor-firmware.service', 'fail')

    def apply_kuzzle_config(self, args):
        if 'kport' in args.keys():
            self.config['kuzzle']['port'] = args['kport']
        if 'khost' in args.keys():
            self.config['kuzzle']['host'] = args['khost']

        with open(self.config_file, mode='w') as f:
            yaml.dump(self.config, f)

        self.restart_firmware()

    def apply_device_config(self, args):
        if 'device_type' in args.keys():
            self.config['device']['type'] = args['device_type']

        if 'owner' in args.keys():
            self.config['device']['owner'] = args['owner']

        with open(self.config_file, mode='w') as f:
            yaml.dump(self.config, f)

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
            print(device_configs)
            admin_template = self.load_admin_template()
            body = admin_template.merge(
                {'config': self.server.config, 'device': {'uid': 'an_uid'}, 'device_configs': device_configs})

            print(body)

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

            dashboard_template = self.load_dashboard_template()
            body = dashboard_template.merge({'config': json.dumps(self.sever.config), 'device': self.server.device_info})

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

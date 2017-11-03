from http.server import *
from http import HTTPStatus
import urllib.parse as uparse
import airspeed
from ruamel.yaml import YAML


class AdminHTTPRequestHandler(SimpleHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/setup':
            content_length = int(self.headers['Content-Length'])
            c = self.rfile.read(content_length)
            args = uparse.parse_qsl(c)
            args = dict([(x[0].decode('utf-8'), x[1].decode('utf-8')) for x in args])
            apply_config(args)

            self.send_response(301)
            self.send_header("Location", "http://" + self.headers["Host"] + '/admin')
            self.end_headers()

    def do_GET(self):
        if self.path == "/admin":
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-type", "text/html")

            admin_template = load_admin_template()
            body = admin_template.merge(config)

            self.send_header("Content-length", len(body))
            self.end_headers()

            self.wfile.write(bytes(body, 'utf-8'))

        elif self.path == "/":
            self.send_response(301)
            self.send_header("Location", "http://" + self.headers["Host"] + '/admin')
            self.end_headers()
        else:
            super().do_GET()


yaml = YAML()
config_update_event = None
server_address = ('', 8083)
httpd = HTTPServer(server_address, AdminHTTPRequestHandler)


def apply_config(args):
    if 'kport' in args.keys():
        config['kuzzle']['port'] = args['kport']
    if 'khost' in args.keys():
        config['kuzzle']['host'] = args['khost']

    with open('config.yaml', mode='w') as f:
        yaml.dump(config, f)

    config_update_event.set()


def start_admin_server(conf_update_event):
    global config_update_event
    config_update_event = conf_update_event
    httpd.serve_forever()


def shutdown_admin_server():
    httpd.shutdown()


def load_admin_template():
    with open('admin/admin.html.vm') as f:
        content = f.read()
    return airspeed.Template(content)


def load_config():
    with open(u"config.yaml") as f:
        config_str = f.read()
    return yaml.load(config_str)


config = load_config()
admin_template = load_admin_template()

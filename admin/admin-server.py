from http.server import *
from http import HTTPStatus
import urllib.parse as uparse
import airspeed
from ruamel.yaml import YAML

yaml = YAML()


def apply_config(args):
    if 'kport' in args.keys():
        config['kuzzle']['port'] = args['kport']
    if 'khost' in args.keys():
        config['kuzzle']['host'] = args['khost']

    print(config)


class AdminHTTPRequestHandler(SimpleHTTPRequestHandler):
    def do_POST(self):
        print('Received a post, path = ', self.path)

        if self.path == '/setup':
            print(self.headers)
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

            body = admin_template.merge(config)

            self.send_header("Content-length", len(body))
            self.end_headers()

            self.wfile.write(bytes(body, 'utf-8'))

        else:
            super().do_GET()


def run():
    server_address = ('', 8083)
    httpd = HTTPServer(server_address, AdminHTTPRequestHandler)
    httpd.serve_forever()


def load_admin_template():
    content = None
    with open('admin.html.vm') as f:
        content = f.read()
    return airspeed.Template(content)


def load_config():
    with open(u"../config.yaml") as f:
        config_str = f.read()

    return yaml.load(config_str)


yaml = YAML()
config = load_config()
admin_template = load_admin_template()
run()

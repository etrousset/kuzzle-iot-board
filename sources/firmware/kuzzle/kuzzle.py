import time
import websockets
import websockets.exceptions as wse
import requests

import asyncio
import json
import logging
import coloredlogs
import sys


class KuzzleIOT(object):
    """ Device state publishing Kuzzle query fmt string"""

    INDEX_IOT = "iot"
    COLLECTION_DEVICE_STATES = "device-state"
    COLLECTION_DEVICE_INFO = "device-info"

    REQUEST_PUBLISH_DEVICE_INFO = "publish_device_info"
    REQUEST_GET_DEVICE_INFO = "get_device_info"

    LOG = logging.getLogger('Kuzzle-IoT')
    JSON_DEC = json.JSONDecoder()

    def __init__(self, device_uid, device_type, host='localhost', port='7512',
                 user: str = '', pwd: str = '', owner: str = None, friendly_name: str = None,
                 additional_info: dict = None):
        self.event_loop = None
        self.host = host
        self.port = port
        self.user = user
        self.pwd = pwd
        self.owner = owner
        self.friendly_name = friendly_name
        self.additional_info = additional_info

        self.url = "ws://{}:{}".format(self.host, self.port)

        self.device_uid = device_uid
        self.device_type = device_type
        self.ws = None
        self.on_connected = None
        self.on_state_changed = None

        coloredlogs.install(logger=KuzzleIOT.LOG,
                            fmt='[%(thread)X] - %(asctime)s - %(name)s - %(levelname)s - %(message)s',
                            level=logging.DEBUG,
                            stream=sys.stdout)

    @staticmethod
    def server_info(host='localhost', port='7512'):
        """
        Get Kuzzle server information. This can be used to validate we are able to reach the server
        """

        url = "http://{}:{}/_serverInfo".format(host, port)
        try:
            req = requests.get(url=url)
            res = json.JSONDecoder().decode(req.text)
            # json.dump(res, sys.stdout, indent=2)
            if res["status"] == 200:
                return res["result"]
            else:
                KuzzleIOT.LOG.critical('Unable to connect to Kuzzle: http://%s:%s', host, port)
                KuzzleIOT.LOG.error(res["error"]["message"])
                KuzzleIOT.LOG.error(res["error"]["stack"])
                return None
        except Exception as e:
            KuzzleIOT.LOG.critical('Unable to connect to Kuzzle: http://%s:%s', host, port)
            return None

    def get_device_info(self):

        query = {
            "index": KuzzleIOT.INDEX_IOT,
            "collection": KuzzleIOT.COLLECTION_DEVICE_INFO,
            "requestId": KuzzleIOT.REQUEST_GET_DEVICE_INFO,
            "controller": "document",
            "action": "get",
            '_id': self.device_uid
        }
        self.post_query(query)

    def publish_device_info(self):
        self.LOG.info("Publishing device info...")
        body = {
            'device_id': self.device_uid,
            'owner': self.owner,
            'friendly_name': self.friendly_name,
            'device_type': self.device_type,
        }

        if self.additional_info:
            body['additional_info'] = self.additional_info

        query = {
            "index": KuzzleIOT.INDEX_IOT,
            "collection": KuzzleIOT.COLLECTION_DEVICE_INFO,
            "requestId": KuzzleIOT.REQUEST_PUBLISH_DEVICE_INFO,
            "controller": "document",
            "action": "createOrReplace",
            "_id": self.device_uid,
            "body": body
        }
        self.LOG.info("%s", query)
        self.post_query(query)

    async def __publish_state_task(self, state, partial):
        body = {
            "device_id": self.device_uid,
            "device_type": self.device_type,
            "partial_state": partial,
            "state": state
        }

        req = {
            "index": KuzzleIOT.INDEX_IOT,
            "collection": KuzzleIOT.COLLECTION_DEVICE_STATES,
            "requestId": "publish_" + self.device_uid,
            "controller": "document",
            "action": "create",
            "body": body
        }
        t = self.post_query(req)
        self.LOG.debug("PUBLISH >>>>")
        return t

    async def __subscribe_state_task(self, on_state_changed: callable):
        self.on_state_changed = on_state_changed
        subscribe_msg = {
            "index": KuzzleIOT.INDEX_IOT,
            "collection": KuzzleIOT.COLLECTION_DEVICE_STATES,
            "controller": "realtime",
            "action": "subscribe",
            "body": {
                "equals": {
                    "device_id": self.device_uid
                }
            }
        }

        return self.post_query(subscribe_msg)

    async def __connect_task(self, on_connected: callable):
        self.LOG.debug("<Connecting.... url = %s>", self.url)
        try:
            self.ws = await websockets.connect(self.url)
        except Exception as e:
            self.LOG.critical(e)
            return

        self.LOG.info("<Connected to %s>", self.url)

        self.on_connected = on_connected

        if self.on_connected:
            self.on_connected(self)

        self.get_device_info()

        self.__run_loop_start()

    def __connect(self, on_connected: callable):
        return self.event_loop.create_task(self.__connect_task(on_connected))

    def __run_loop_start(self):
        self.event_loop.create_task(self.__run_loop_task())

    def on_device_info_resp(self, resp):
        self.LOG.debug("device info result")
        if resp['status'] != 200:
            self.publish_device_info()

    async def __run_loop_task(self):
        while 1:
            self.LOG.debug("%s: <<Waiting for data from Kuzzle...>>", self.device_type)
            try:
                resp = await asyncio.wait_for(self.ws.recv(), timeout=60)
            except wse.ConnectionClosed as e:
                self.LOG.error('__publish_state_task: ws disconnection: %s', str(e))
                self.LOG.info('reconnecting in 5s...')
                time.sleep(5)

                try:
                    self.ws = await websockets.connect(self.url)
                    self.LOG.debug('Re subscribing to own state...')
                    self.subscribe_state(self.on_state_changed)
                except Exception as e:
                    self.LOG.critical(e)
                continue
            except asyncio.TimeoutError:
                try:
                    self.LOG.info("PING Kuzzle")
                    pong_waiter = await self.ws.ping()
                    await asyncio.wait_for(pong_waiter, timeout=10)
                    self.LOG.info("PONG Kuzzle")
                except asyncio.TimeoutError:
                    self.LOG.critical("No PONG from Kuzzle")
                    break
                continue
            except Exception as e:
                self.LOG.error('__publish_state_task: ws except: %s', str(e))

            self.LOG.debug("%s: <<Received data from Kuzzle...>>", self.device_type)
            resp = json.loads(resp)
            # print(json.dumps(resp, indent=2, sort_keys=True))

            if resp["status"] != 200:
                print(json.dumps(resp, indent=2, sort_keys=True))

            if resp["action"] in ['replace', 'create'] and self.on_state_changed and resp[
                "requestId"] != "publish_" + self.device_uid:
                source = resp["result"]["_source"]

                is_partial = source["is_partial"] if "state_partial" in source else False
                self.on_state_changed(source["state"], is_partial)
            elif resp['requestId'] == KuzzleIOT.REQUEST_GET_DEVICE_INFO:
                self.on_device_info_resp(resp)

    def subscribe_state(self, on_state_changed: callable):
        self.LOG.debug("%s: <<Adding task to subscribe state>>", self.device_type)
        return self.event_loop.create_task(self.__subscribe_state_task(on_state_changed))

    async def __post_query_task(self, query: dict, cb: callable = None):
        self.LOG.debug("%s: Posting query", self.device_type)
        await self.ws.send(json.dumps(query))
        if cb:
            cb()
        self.LOG.debug("%s: Query posted", self.device_type)

    def post_query(self, query: dict, cb: callable = None):
        self.LOG.debug("%s: <<Adding task to post a query>>", self.device_type)
        return self.event_loop.create_task(self.__post_query_task( query, cb))

    def publish_state(self, state, partial=False):
        self.LOG.debug("%s: <<Adding task to publish state>>", self.device_type)
        return asyncio.run_coroutine_threadsafe(self.__publish_state_task(state, partial), self.event_loop)

    def connect(self, on_connected: callable):
        print("<Connect>")
        self.event_loop = asyncio.get_event_loop()
        assert self.event_loop, "No event loop found"
        # return self.event_loop.run_in_executor(None, self.__connect, on_connected)
        return self.__connect(on_connected)

    def disconnect(self):
        self.ws.close()

import websockets
import websockets.http as http
import http.client as httpclient
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

    PUBLISH_DEVICE_STATE_FMT = """
    { 
        "index": "{K_INDEX_IOT}", 
        "collection":" {K_COLLECTION_DEVICE_STATES}", 
         "body": {
            "device_id" : "{K_DEVICE_ID} ", 
            "device_type":"{K_DEVICE_TYPE}", 
            "state" : {K_DEVICE_STATE}
        }
    }"""

    LOG = logging.getLogger('Kuzzle-IoT')
    JSON_DEC = json.JSONDecoder()

    def __init__(self, device_uid, device_type, host='localhost', port='7512',
                 user='', pwd=''):
        self.event_loop = None
        self.host = host
        self.port = port
        self.user = user
        self.pwd = pwd

        self.device_uid = device_uid
        self.device_type = device_type
        self.ws = None
        self.on_connected = None
        self.on_state_changed = None

        coloredlogs.install(logger=KuzzleIOT.LOG,
                            fmt='[%(thread)d] - %(asctime)s - %(name)s - %(levelname)s - %(message)s',
                            level=logging.DEBUG,
                            stream=sys.stdout)

    def server_info(self):
        """
        Ping Kuzzle to validate where are able to reach
        """

        url = "http://{}:{}/_serverInfo".format(self.host, self.port)
        try:
            req = requests.get(url=url)
            res = self.JSON_DEC.decode(req.text)
            # json.dump(res, sys.stdout, indent=2)
            if res["status"] == 200:
                return res["result"]
            else:
                self.LOG.critical('Unable to connect to Kuzzle: http://%s:%s', self.host, self.port)
                self.LOG.error(res["error"]["message"])
                self.LOG.error(res["error"]["stack"])
                return None
        except Exception as e:
            self.LOG.critical('Unable to connect to Kuzzle: http://%s:%s', self.host, self.port)
            return None

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
        await self.ws.send(json.dumps(req))

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
        await self.ws.send(json.dumps(subscribe_msg))

    async def __connect_task(self, on_connected: callable):
        url = "ws://{}:{}".format(self.host, self.port)
        self.LOG.debug("<Connecting.... url = %s>", url)
        try:
            self.ws = await websockets.connect(url)
        except Exception as e:
            self.LOG.critical(e)
            return

        self.LOG.info("<Connected to %s>", url)

        self.on_connected = on_connected

        if self.on_connected:
            self.on_connected(self)

        self.event_loop.run_in_executor(None, self.__run_loop_start)

    def __connect(self, on_connected: callable):
        return self.event_loop.create_task(self.__connect_task(on_connected))

    def __run_loop_start(self):
        self.event_loop.create_task(self.__run_loop_task())

    async def __run_loop_task(self):
        while 1:
            self.LOG.debug("<<Waiting for data from Kuzzle...>>")
            resp = await self.ws.recv()
            self.LOG.debug("<<Received data from Kuzzle...>>")
            resp = json.loads(resp)
            # print(json.dumps(resp, indent=2, sort_keys=True))

            if resp["status"] != 200:
                print(json.dumps(resp, indent=2, sort_keys=True))
                return

            if resp["action"] in ['replace', 'create'] and self.on_state_changed and resp[
                "requestId"] != "publish_" + self.device_uid:
                source = resp["result"]["_source"]

                is_partial = source["is_partial"] if "state_partial"  in source else False
                self.on_state_changed(source["state"], is_partial)

    def __subscribe_state(self, on_state_changed: callable):
        self.LOG.debug("Adding task to subscribe to state change")
        return self.event_loop.create_task(self.__subscribe_state_task(on_state_changed))

    def subscribe_state(self, on_state_changed: callable):
        self.LOG.debug("<<Adding task to subscribe state>>")
        return self.event_loop.run_in_executor(None, self.__subscribe_state, on_state_changed)

    def __publish_state(self, state, partial):
        self.LOG.debug("Adding task to publish state")
        return self.event_loop.create_task(self.__publish_state_task(state, partial))

    def publish_state(self, state, partial=False):
        self.LOG.debug("<<Adding task to publish state>>")
        return self.event_loop.run_in_executor(None, self.__publish_state, state, partial)

    def connect(self, on_connected: callable):
        print("<Connect>")
        self.event_loop = asyncio.get_event_loop()
        assert self.event_loop, "No event loop found"
        # return self.event_loop.run_in_executor(None, self.__connect, on_connected)
        return self.__connect(on_connected)

    def disconnect(self):
        self.ws.close()

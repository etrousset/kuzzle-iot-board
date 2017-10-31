import requests
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

    LOG = logging.getLogger('Kuzzle')
    JSON_DEC = json.JSONDecoder()

    def __init__(self, device_uid, device_type, host='localhost', port='7512',
                 user='', pwd=''):
        self.host = host
        self.port = port
        self.user = user
        self.pwd = pwd

        self.device_uid = device_uid
        self.device_type = device_type

        coloredlogs.install(logger=KuzzleIOT.LOG,
                            fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
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

    def publish_state(self, state):
        url = "http://{}:{}/{}/{}/_create".format(self.host, self.port, KuzzleIOT.INDEX_IOT,
                                                  KuzzleIOT.COLLECTION_DEVICE_STATES)
        body = {
            "device_id": self.device_uid,
            "device_type": self.device_type,
            "state": state
        }
        req = requests.post(url=url, json=body)
        res = self.JSON_DEC.decode(req.text)

        if res['status'] != 200:
            self.LOG.error("Error publishing device state: status = %d", res['status'])
            self.LOG.error("\tMessage: %s", res['error']['message'])
            self.LOG.error("\tStack: \n%s", res['error']['stack'])

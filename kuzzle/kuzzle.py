import requests


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

    def __init__(self, device_uid, device_type, host='localhost', port='7512',
                 user='', pwd=''):
        self.host = host
        self.port = port
        self.user = user
        self.pwd = pwd

        self.device_uid = device_uid
        self.device_type = device_type

        pass

    def publish_state(self, state):
        url = "http://{}:{}/{}/{}/_create".format(self.host, self.port, KuzzleIOT.INDEX_IOT,
                                                  KuzzleIOT.COLLECTION_DEVICE_STATES)
        body = {
            "device_id": self.device_uid,
            "device_type": self.device_type,
            "state": state
        }
        req = requests.post(url=url, json=body)

        print(req.text)

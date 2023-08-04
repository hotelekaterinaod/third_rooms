import json
import logging

FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

logging.basicConfig(filename='debug.log', format=FORMAT)
logger = logging.getLogger("main")

logger.setLevel(level=logging.DEBUG)

# create console handler and set level to debug
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)

# create formatter
formatter = logging.Formatter(FORMAT)

# add formatter to ch
ch.setFormatter(formatter)

# add ch to logger
logger.addHandler(ch)


class DBConfig:

    def __init__(self, db_config_data):
        self.server = db_config_data["server"]
        self.user = db_config_data["user"]
        self.password = db_config_data["password"]
        self.database = db_config_data["database"]


class Config:

    def __init__(self):
        with open("config.json") as cf:
            config_data = json.loads(cf.read())
        self.room_number = config_data["room_number"]
        self.db_config = DBConfig(config_data["db_config"])
        self.lock_timeout = config_data["lock_timeout"]
        self.new_key_check_interval = config_data["new_key_check_interval"]
        self.rfig_key_table_index = config_data["rfig_key_table_index"]
        self.rfid_key_length = config_data["rfid_key_length"]
        self.check_pin_timeout = config_data["check_pin_timeout"]


system_config = Config()

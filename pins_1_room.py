#! /usr/bin/env python
# -*- coding: utf-8 -*-
import threading
import time
import signal
import smbus
from datetime import datetime, timedelta
import pymssql
import serial
import RPi.GPIO as GPIO
from retry import retry
import logging

from pin_controller import PinController
from relaycontroller import RelayController
from config import system_config, logger

door_just_closed = False
can_open_the_door = False
close_door_from_inside = False
count_keys = 0
room_controller = {}

db_connection = None

bus = smbus.SMBus(1)

# адреса контроллеров
relay1_controller = RelayController(0x38)

# соответствие портов контроллеров
relay1_controller.set_bit(0)  # открыть замок
relay1_controller.set_bit(1)  # закрыть замок
relay1_controller.set_bit(2)  # кнопка внутреннего открытия


data1 = bus.read_byte(0x38)


logger.info(str(bin(data1)))

active_cards = {}
active_key = None

GPIO.setmode(GPIO.BCM)

close_door_from_inside_counter = 1
open_door_counter = 1


class ProgramKilled(Exception):
    pass


# GPIO_18 callback (использование кнопок)
def f_using_keys(self):
    logger.info("Use keys")
    permit_open_door()
    # relay1_controller.clear_bit(2)
    # time.sleep(0.2)
    # relay1_controller.set_bit(2)

def f_using_homephone(self):
    logger.info("Use key2")
    permit_open_door(homephone=True)
    # relay1_controller.clear_bit(2)
    # time.sleep(0.2)
    # relay1_controller.set_bit(2)


def init_room():
    logger.info("Init room")
    pin_structure = {
        24: PinController(24, f_using_keys),  # (открытие замка механическим ключем)
        21: PinController(21, f_using_homephone)
    }

    global bus
    logger.info("The room has been initiated")
    return pin_structure





# открытие замка с предварительной проверкой положения pin23(защелка, запрет) и последующим закрытием по таймауту
@retry(tries=10, delay=1)
def permit_open_door(homephone=False):
    if not homephone:
        relay1_controller.clear_bit(2)
        time.sleep(0.2)
        relay1_controller.set_bit(2)
    relay1_controller.clear_bit(0)
    time.sleep(0.2)
    relay1_controller.set_bit(0)

    time.sleep(4.25)
    close_door()


# закрытие замка, с предварительной проверкой
@retry(tries=10, delay=1)
def close_door(thread_time=None):
    time.sleep(0.1)
    relay1_controller.clear_bit(1)
    time.sleep(0.115)
    relay1_controller.set_bit(1)
    logger.info("Someone has been entered!")


def handle_table_row(row_):
    return row_[system_config.rfig_key_table_index].replace(" ", "")


def get_db_connection():
    global db_connection
    if db_connection is None:
        db_connection = pymssql.connect(**system_config.db_config.__dict__)
    return db_connection


@retry(tries=3, delay=1)
def get_active_cards():
    global active_cards, count_keys
    cursor = get_db_connection().cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sql = "SELECT * FROM table_kluch WHERE dstart <= '{now}' AND dend >= '{now}' AND num = {" \
          "room_number}".format(now=now, room_number=system_config.room_number)
    cursor.execute(sql)
    key_list = cursor.fetchall()
    active_cards = {handle_table_row(key): key for key in key_list}

    if count_keys != len(key_list):
        sql_update = "UPDATE table_kluch SET rpi = 1 WHERE dstart <= '{now}' AND dend >= '{now}' AND num = {" \
                     "room_number}".format(now=now, room_number=system_config.room_number)
        cursor.execute(sql_update)
        get_db_connection().commit()
        count_keys = len(key_list)
        logger.info("Success update rpi field for new keys")


@retry(tries=10, delay=1)
def wait_rfid():
    try:
        logger.info("Search key")
        rfid_port = serial.Serial('/dev/ttyS0', 9600)
        read_byte = (rfid_port.read(system_config.rfid_key_length)[1:11])
        key_ = read_byte.decode("utf-8")
        rfid_port.close()
        if key_:
            logger.info("key catched {key} {datetime}".format(key=key_, datetime=datetime.utcnow()))
            return key_
        else:
            logger.info(f"No key {key_}")
    except Exception as e:
        print(f"Error in rfid {e}")
        pass



@retry(tries=3, delay=5)
def check_pins():
    global room_controller
    pin_list_for_check = [21, 24]
    for item in pin_list_for_check:
        room_controller[item].check_pin()
    state_message = "Pin state : "
    for item in pin_list_for_check:
        state_message += "pin#{pin}:{state}, ".format(pin=room_controller[item].pin, state=room_controller[item].state)
    print(state_message)


def signal_handler(signum, frame):
    raise ProgramKilled


class CheckPinTask(threading.Thread):

    def __init__(self, interval, execute):
        threading.Thread.__init__(self)
        self.daemon = False
        self.stopped = threading.Event()
        self.interval = interval
        self.execute = execute

    def stop(self):
        self.stopped.set()
        self.join()

    def run(self):
        while not self.stopped.wait(self.interval.total_seconds()):
            self.execute()


class CheckActiveCardsTask(threading.Thread):
    def __init__(self, interval, execute, *args, **kwargs):
        threading.Thread.__init__(self)
        self.daemon = False
        self.stopped = threading.Event()
        self.interval = interval
        self.execute = execute
        self.args = args
        self.kwargs = kwargs

    def stop(self):
        self.stopped.set()
        self.join()

    def run(self):
        while not self.stopped.wait(self.interval.total_seconds()):
            self.execute(*self.args, **self.kwargs)


def main():
    global room_controller, door_just_closed, active_key
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    get_active_cards()
    card_task = CheckActiveCardsTask(interval=timedelta(seconds=system_config.new_key_check_interval),
                                     execute=get_active_cards)
    card_task.start()

    room_controller = init_room()

    check_pins()
    check_pin_task = CheckPinTask(interval=timedelta(seconds=system_config.check_pin_timeout), execute=check_pins)
    check_pin_task.start()

    while True:
        try:
            logger.info("Waiting for the key")
            door_just_closed = False

            entered_key = wait_rfid()


            print("Entered key: {entered_key}".format(entered_key=entered_key))
            if entered_key in list(active_cards.keys()):
                active_key = active_cards[entered_key]
                logger.info("Correct key! Please enter!")
                permit_open_door()

            else:
                logger.info("Unknown key!")

        except ProgramKilled:
            logger.info("Program killed: running cleanup code")
            card_task.stop()
            check_pin_task.stop()
            break


if __name__ == "__main__":
    logging.basicConfig()
    main()

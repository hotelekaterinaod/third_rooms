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
lighting_main = False  # переменная состояния основного света спальня1
lighting_bl = False  # переменная состояния бра левый спальня1
lighting_br = False  # переменная состояния бра правый спальня1

lighting_main2 = False  # переменная состояния основного света спальня2
lighting_bl2 = False  # переменная состояния бра левый спальня2
lighting_br2 = False  # переменная состояния бра правый спальня2

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


# def f_lock_door_from_inside(self):
#     # logger.info(f"OFFF {bool(room_controller[23].state)}")
#     if bool(room_controller[23].state):
#         relay2_controller.clear_bit(6)  # 6


# GPIO_23 callback (проверка сработки внут защелки (ригеля) на закрытие)
# def f_lock_door_from_inside_thread():
#     while not bool(room_controller[23].state):
#         relay2_controller.set_bit(6)  # 6
#         time.sleep(0.2)
#         relay2_controller.clear_bit(6)  # 6
#         time.sleep(0.2)


# def f_open_door_indicates_thread():
#     for i in range(12):
#         relay2_controller.set_bit(4)  # 6
#         time.sleep(0.2)
#         relay2_controller.clear_bit(4)  # 6
#         time.sleep(0.2)


# def f_before_lock_door_from_inside(self):
#     global close_door_from_inside
#     time.sleep(0.01)
#     thread_time = threading.Thread(target=f_lock_door_from_inside_thread)
#     thread_time.start()
#     if self.state:
#         thread_time.join()
#         relay2_controller.clear_bit(6)  # тушим красный светодиод


# GPIO_24 callback (проверка сработки "язычка" на открытие)
# def f_lock_latch(self):
#     time.sleep(1)
#     logger.info("Lock latch")
#     # close_door()


# GPIO_18 callback (использование ключа)
def f_using_key(self):
    logger.info("Use key")
    relay1_controller.clear_bit(2)

def f_using_key2(self):
    logger.info("Use key2")
    relay1_controller.clear_bit(2)


# GPIO_10 callback (сейф)
# def f_safe(self):
#     logger.info("Safe")
#     pass
#
#
#
# # GPIO_22 callback картоприемник
# def f_card_key(self):
#     logger.info("Card")
#     pass


# GPIO_27 callback цепь автоматов
# def f_circuit_breaker(self):
#     logger.info("Curcuit breaker")
#     pass


# def is_door_locked_from_inside():
#     global room_controller
#     time.sleep(0.1)
#     logger.info(f"Is door locked {not bool(room_controller[23].state)}")
#     return not bool(room_controller[23].state)


def init_room():
    logger.info("Init room")
    pin_structure = {
        0: None,
        1: None,
        #1: PinController(1, f_switch_br, react_on=GPIO.FALLING, bouncetime=200),
        # кнопка-выключатель бра правый спальня1,
        2: None,
        3: None,
        5: None,
        6: None,
        7: None,  # (окно2)
        8: None,  # датчик дыма 4,
        9: None,
        10: None,
        11: None,  # кнопка-выключатель бра правый спальня2,
        12: None,
        # кнопка-выключатель бра левый спальня1
        13: None,  # (окно3)
        14: None,
        15: None,
        16: None,
        # кнопка-выключатель основного света спальня1
        17: None,
        # (контроль наличия питания R3 (освещения))
        24: PinController(24, f_using_key),  # (открытие замка механическим ключем)
        19: None,  # (датчик дыма 2)
        20: None,  # (окно1-балкон)

        22: None,
        23: None,
        # замок "запрет"
        25: None,  # датчик дыма 1
        26: None,  # датчик дыма 3
        27: None,
        21: PinController(21, f_using_key2),
        # (цепь допконтактов автоматов)
    }

    global bus
    logger.info("The room has been initiated")
    return pin_structure





# открытие замка с предварительной проверкой положения pin23(защелка, запрет) и последующим закрытием по таймауту
@retry(tries=10, delay=1)
def permit_open_door():
    global door_just_closed, can_open_the_door, active_key
    # if is_door_locked_from_inside():
    #     logger.info("The door has been locked by the guest.")
    #     for i in range(10):
    #         relay2_controller.set_bit(4)
    #         time.sleep(0.2)
    #         relay2_controller.clear_bit(4)
    #         time.sleep(0.2)


    relay1_controller.clear_bit(1)
    time.sleep(0.115)
    relay1_controller.set_bit(1)
    time.sleep(4.25)
    close_door()


# закрытие замка, с предварительной проверкой
@retry(tries=10, delay=1)
def close_door(thread_time=None):
    global door_just_closed, can_open_the_door


    time.sleep(0.1)
    relay1_controller.clear_bit(0)
    time.sleep(0.115)
    relay1_controller.set_bit(0)
    logger.info("Client has been entered!")


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
    logger.info("Search key")
    rfid_port = serial.Serial('/dev/ttyS0', 9600)
    print(rfid_port)
    read_byte = (rfid_port.read(system_config.rfid_key_length)[1:11])
    print(read_byte)
    key_ = read_byte.decode("utf-8")
    rfid_port.close()
    print(key_)
    if key_:
        logger.info("key catched {key} {datetime}".format(key=key_, datetime=datetime.utcnow()))
        return key_
    else:
        logger.info(f"No key {key_}")


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

                # if is_door_locked_from_inside():
                #     relay2_controller.clear_bit(4)
        except ProgramKilled:
            logger.info("Program killed: running cleanup code")
            card_task.stop()
            check_pin_task.stop()
            break


if __name__ == "__main__":
    logging.basicConfig()
    main()

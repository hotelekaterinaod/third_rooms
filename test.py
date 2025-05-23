#!/usr/bin/env python
# -*- coding: utf-8 -*-
import threading
import time
import signal
import smbus
from datetime import datetime, timedelta
import pymssql
import serial
import pigpio
from retry import retry
import logging
import multiprocessing

from test_controller import PinController
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

is_sold = False
prev_is_sold = is_sold
is_empty = True
timer_thread = None
off_timer_thread = None
second_light_thread = None

db_connection = None

bus = smbus.SMBus(1)

# адреса контроллеров
relay1_controller = RelayController(0x38)
relay2_controller = RelayController(0x39)

# соответствие портов контроллеров
relay1_controller.set_bit(0)  # открыть замок
relay1_controller.set_bit(1)  # закрыть замок
relay1_controller.set_bit(2)  # аварийное освещение
relay1_controller.set_bit(3)  # соленоиды
relay1_controller.set_bit(4)  # R2
relay1_controller.set_bit(5)  # R3
relay1_controller.set_bit(6)  # бра левый
relay1_controller.set_bit(7)  # бра правый

relay2_controller.set_bit(0)  # свет спальня
relay2_controller.set_bit(1)  # кондиционеры
relay2_controller.set_bit(2)  # радиатор1
relay2_controller.set_bit(3)  # радиатор2
relay2_controller.clear_bit(4)  # зеленый
relay2_controller.clear_bit(5)  # синий
relay2_controller.clear_bit(6)  # красный
relay2_controller.set_bit(7)  # свет спальня спальня2

data1 = bus.read_byte(0x38)
data2 = bus.read_byte(0x39)

logger.info(str(bin(data1) + " " + bin(data2)))

active_cards = {}
logs = {}
active_key = None

# Инициализация pigpio
pi = pigpio.pi()
if not pi.connected:
    raise RuntimeError("Не удалось подключиться к pigpio")

close_door_from_inside_counter = 1
open_door_counter = 1


class ProgramKilled(Exception):
    pass


def f_lock_door_from_inside(self):
    if bool(room_controller[23].state):
        relay2_controller.clear_bit(6)  # 6


def f_lock_door_from_inside_thread():
    while not bool(room_controller[23].state):
        relay2_controller.set_bit(6)  # 6
        time.sleep(0.2)
        relay2_controller.clear_bit(6)  # 6
        time.sleep(0.2)


def f_open_door_indicates_thread():
    for i in range(12):
        relay2_controller.set_bit(4)  # 6
        time.sleep(0.2)
        relay2_controller.clear_bit(4)  # 6
        time.sleep(0.2)


def f_before_lock_door_from_inside(self):
    global close_door_from_inside
    time.sleep(0.01)
    thread_time = threading.Thread(target=f_lock_door_from_inside_thread)
    thread_time.start()
    if self.state:
        thread_time.join()
        relay2_controller.clear_bit(6)  # тушим красный светодиод


def f_lock_latch(gpio, level, tick):
    time.sleep(1)
    logger.info("Lock latch")


def f_using_key(gpio, level, tick):
    logger.info("Use key")


def f_safe(gpio, level, tick):
    logger.info("Safe")


def f_fire_detector1(gpio, level, tick):
    logger.info("Fire detector 1")


def f_fire_detector2(gpio, level, tick):
    logger.info("Fire detector 2")


def f_fire_detector3(gpio, level, tick):
    logger.info("Fire detector 3")


def f_fire_detector4(gpio, level, tick):
    logger.info("Fire detector 4")


def start_timer(func, type=1):
    global timer_thread, off_timer_thread
    logger.info(f"Start timer type {type}")
    if type == 1:
        delay_seconds = int(system_config.t1_timeout * 60)
        timer_thread = multiprocessing.Process(target=func, args=(delay_seconds,))
        timer_thread.start()
    elif type == 2:
        delay_seconds = int(system_config.t2_timeout * 60)
        off_timer_thread = multiprocessing.Process(target=func, args=(delay_seconds,))
        off_timer_thread.start()


def timer_turn_everything_off(time_seconds):
    time.sleep(time_seconds)
    turn_everything_off()


def turn_on(type=1):
    global lighting_bl, lighting_br, lighting_main
    logger.info("Turn everything on")
    relay1_controller.clear_bit(3)  # соленоиды
    relay1_controller.clear_bit(4)  # R2
    relay1_controller.clear_bit(5)  # R3
    relay2_controller.clear_bit(1)  # кондиционер
    if type == 1:
        start_timer(timer_turn_everything_off)


def f_card_key(gpio, level, tick):
    logger.info("Card")
    global active_key, is_sold
    card_role = get_card_role(active_key)
    logger.info(card_role)
    if not is_sold:
        if card_role == "Admin" or card_role == "Worker":
            print("Включение для работника или админа")
            turn_on()
    else:
        print("Выключение")
        turn_on(type=2)


def f_circuit_breaker(gpio, level, tick):
    logger.info("Curcuit breaker")


def f_energy_sensor(gpio, level, tick):
    logger.info("Energy sensor work")


def f_window1(gpio, level, tick):
    logger.info("window 1")


def f_window2(gpio, level, tick):
    logger.info("window 2")


def f_window3(gpio, level, tick):
    logger.info("window 3")


def f_switch_main(gpio, level, tick):
    global lighting_main
    if not lighting_main:
        relay2_controller.clear_bit(0)
        lighting_main = True
    else:
        relay2_controller.set_bit(0)
        lighting_main = False


def f_switch_bl(gpio, level, tick):
    global lighting_bl
    if not lighting_bl:
        relay1_controller.clear_bit(6)
        lighting_bl = True
    else:
        relay1_controller.set_bit(6)
        lighting_bl = False


def f_switch_br(gpio, level, tick):
    global lighting_br
    if not lighting_br:
        relay1_controller.clear_bit(7)
        lighting_br = True
    else:
        relay1_controller.set_bit(7)
        lighting_br = False


def f_flooding_sensor(gpio, level, tick):
    logger.info("flooding_sensor")


def is_door_locked_from_inside():
    global room_controller
    time.sleep(0.1)
    logger.info(f"Door is locked - {not bool(room_controller[23].state)}")
    return not bool(room_controller[23].state)


def cardreader_before(self):
    pass


def init_room():
    logger.info("Init room")
    pin_structure = {
        0: None,
        1: PinController(pi, 1, f_switch_br),
        7: PinController(pi, 7, f_window2),
        8: PinController(pi, 8, f_fire_detector4),
        10: PinController(pi, 10, f_safe),
        12: PinController(pi, 12, f_switch_bl),
        13: PinController(pi, 13, f_window3),
        16: PinController(pi, 16, f_switch_main),
        17: PinController(pi, 17, f_energy_sensor),
        18: PinController(pi, 18, f_using_key),
        19: PinController(pi, 19, f_fire_detector2),
        20: PinController(pi, 20, f_window1),
        21: PinController(pi, 21, f_flooding_sensor),
        22: PinController(pi, 22, f_card_key),
        23: PinController(pi, 23, f_lock_door_from_inside),
        24: PinController(pi, 24, f_lock_latch),
        25: PinController(pi, 25, f_fire_detector1),
        26: PinController(pi, 26, f_fire_detector3),
        27: PinController(pi, 27, f_circuit_breaker),
    }

    global bus
    logger.info("The room has been initiated")
    return pin_structure


def get_card_role(card):
    global active_cards
    if card:
        try:
            tip_index = int(card[5])
        except:
            tip_index = 26
        if 0 <= tip_index <= 1:
            return "User"
        elif 2 <= tip_index <= 8:
            return "Worker"
        elif tip_index == 9:
            return "Admin"
        else:
            return None
    else:
        return None


def second_light_control():
    logger.info("Start timer type 3")
    relay1_controller.clear_bit(2)
    time.sleep(system_config.t3_timeout)
    relay1_controller.set_bit(2)


@retry(tries=10, delay=1)
def permit_open_door():
    global door_just_closed, can_open_the_door, active_key, second_light_thread
    card_role = get_card_role(active_key)
    logger.info(f"Card role: {card_role}")
    if is_door_locked_from_inside() and card_role != "Admin":
        logger.info("The door has been locked by the guest.")
        for i in range(10):
            relay2_controller.set_bit(4)
            time.sleep(0.2)
            relay2_controller.clear_bit(4)
            time.sleep(0.2)
    else:
        can_open_the_door = True
        thread_time = threading.Thread(target=f_open_door_indicates_thread)
        thread_time.start()

        relay1_controller.clear_bit(1)
        time.sleep(0.115)
        relay1_controller.set_bit(1)
        second_light_thread = multiprocessing.Process(target=second_light_control)
        second_light_thread.start()
        time.sleep(4.25)
        close_door(thread_time)


@retry(tries=10, delay=1)
def close_door(thread_time=None):
    global door_just_closed, can_open_the_door
    if not can_open_the_door:
        logger.info("Door is closed. Permission denied!")
        return
    can_open_the_door = False
    door_just_closed = True
    time.sleep(0.1)
    relay1_controller.clear_bit(0)
    time.sleep(0.115)
    relay1_controller.set_bit(0)
    if thread_time:
        thread_time.join()
    relay2_controller.clear_bit(4)
    logger.info("Client has been entered!")


def handle_table_row(row_):
    return row_[system_config.rfig_key_table_index].replace(" ", "")


def get_db_connection():
    global db_connection
    if db_connection is None:
        db_connection = pymssql.connect(**system_config.db_config.__dict__)
    return db_connection


def turn_everything_off():
    global lighting_bl, lighting_br, lighting_main, is_sold
    logger.info("Turn everything off")
    relay1_controller.set_bit(3)  # соленоиды
    if not is_sold:
        relay1_controller.set_bit(4)  # R2
    relay1_controller.set_bit(5)  # R3
    relay1_controller.set_bit(6)  # бра левый
    relay1_controller.set_bit(7)  # бра правый
    lighting_br = False
    lighting_bl = False
    lighting_main = False
    relay2_controller.set_bit(0)
    relay2_controller.set_bit(1)
    relay2_controller.set_bit(7)


@retry(tries=3, delay=1)
def get_active_cards():
    global active_cards, count_keys, is_sold, prev_is_sold
    cursor = get_db_connection().cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sql = "SELECT * FROM table_kluch WHERE dstart <= '{now}' AND dend >= '{now}' AND num = {" \
          "room_number} and tip IS NOT NULL AND tip >= 0 AND tip <= 9 ".format(now=now, room_number=system_config.room_number)
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

    if key_list:
        is_sold = False
        for key in key_list:
            card_role = get_card_role(key)

            if card_role == "User":
                print(key, "Is user")
                is_sold = True
                break
        logger.info(f"is_sold {is_sold}")
        if prev_is_sold != is_sold:
            if not is_sold:
                turn_everything_off()
            else:
                relay1_controller.clear_bit(4)  # R2
            prev_is_sold = is_sold


@retry(tries=10, delay=1)
def wait_rfid():
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


@retry(tries=3, delay=5)
def check_pins():
    global room_controller
    pin_list_for_check = [1, 7, 8, 10, 12, 13, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27]
    for item in pin_list_for_check:
        room_controller[item].check_pin()
    state_message = "Pin state : "
    for item in pin_list_for_check:
        state_message += "pin#{pin}:{state}, ".format(pin=room_controller[item].pin, state=room_controller[item].state)
    logger.info(state_message)


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


class CheckCardTask(threading.Thread):

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


from typing import Union

from fastapi import FastAPI, Depends, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

app = FastAPI()
templates = Jinja2Templates(directory="/home/pi/software/third_rooms/templates")

app.mount("/static", StaticFiles(directory="/home/pi/software/third_rooms/static"), name="static")


@app.get("/")
def read_root():
    return {"Hello": "World"}


@app.get('/get_input/')
async def get_input():
    global room_controller
    states = []
    for i in range(27):
        try:
            states.append({"pin" + str(i): "state = " + str(bool(room_controller[i].state))})
        except Exception:
            pass

    return states


@app.get('/logs/')
async def get_logs(request: Request):
    log_file = 'debug.log'
    try:
        with open(log_file, 'r') as f:
            logs = f.readlines()
        reversed_list = logs[::-1]
        return templates.TemplateResponse("index.html", {'request': request, "file_content": reversed_list})

    except FileNotFoundError:
        return {'error': 'Log file not found'}


prev_card_present = True


def cardreader_find():
    global is_empty, timer_thread, off_timer_thread, prev_card_present, second_light_thread
    card_present = not pi.read(22)  # Считывание состояния пина через pigpio
    print("Карта GPIO ", card_present)
    if card_present:
        print("Карта обнаружена")
        is_empty = False
        if prev_card_present != card_present:
            prev_card_present = card_present
        if off_timer_thread:
            off_timer_thread.terminate()
            logger.info("Stop timer type 2")
            off_timer_thread = None
        if second_light_thread:
            second_light_thread.terminate()
            logger.info("Stop timer type 3")
            second_light_thread = None
    else:
        if timer_thread:
            timer_thread.terminate()
            logger.info("Stop timer type 1")
            timer_thread = None
        print("Карта не обнаружена")
        is_empty = True
        if prev_card_present != card_present:
            start_timer(timer_turn_everything_off, 2)
            prev_card_present = card_present


def main():
    global room_controller, door_just_closed, active_key
    print("Start main function")

    get_active_cards()
    card_task = CheckActiveCardsTask(interval=timedelta(seconds=system_config.new_key_check_interval),
                                     execute=get_active_cards)
    card_task.start()

    room_controller = init_room()

    check_pins()
    check_pin_task = CheckPinTask(interval=timedelta(seconds=system_config.check_pin_timeout), execute=check_pins)
    check_pin_task.start()

    cardreader_find()
    cardreader_task = CheckCardTask(interval=timedelta(seconds=4), execute=cardreader_find)
    cardreader_task.start()

    while True:
        try:
            logger.info("Waiting for the key")
            door_just_closed = False

            entered_key = wait_rfid()
            if entered_key in list(active_cards.keys()):
                active_key = active_cards[entered_key]
                logger.info("Correct key! Please enter!")
                permit_open_door()

            else:
                logger.info("Unknown key!")
                for i in range(15):
                    relay2_controller.set_bit(6)
                    time.sleep(0.1)
                    relay2_controller.clear_bit(6)
                    time.sleep(0.1)

        except ProgramKilled:
            logger.info("Program killed: running cleanup code")
            card_task.stop()
            check_pin_task.stop()
            break


@app.on_event("startup")
async def on_startup():
    print("Starting server...")
    logging.basicConfig()
    print("Server started")


thread = threading.Thread(target=main)
thread.start()

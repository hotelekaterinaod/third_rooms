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
import multiprocessing

from pin_controller import PinController
from relaycontroller import RelayController
from config import system_config, logger


def setup_logging():
    """Настройка системы логирования с форматированием и ротацией файлов"""
    from logging.handlers import RotatingFileHandler
    import os
    
    # Создаем директорию для логов, если ее нет
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # Настройка основного логгера
    main_handler = RotatingFileHandler(
        os.path.join(log_dir, 'main.log'), 
        maxBytes=10*1024*1024,  # 10 MB
        backupCount=5
    )
    main_formatter = logging.Formatter('%(asctime)s [%(levelname)s] - %(message)s')
    main_handler.setFormatter(main_formatter)
    
    # Настройка логгера для событий реле
    relay_handler = RotatingFileHandler(
        os.path.join(log_dir, 'relay.log'), 
        maxBytes=5*1024*1024,  # 5 MB
        backupCount=3
    )
    relay_formatter = logging.Formatter('%(asctime)s - %(message)s')
    relay_handler.setFormatter(relay_formatter)
    
    # Настройка логгера для событий карт
    card_handler = RotatingFileHandler(
        os.path.join(log_dir, 'cards.log'), 
        maxBytes=5*1024*1024,  # 5 MB
        backupCount=3
    )
    card_formatter = logging.Formatter('%(asctime)s - %(message)s')
    card_handler.setFormatter(card_formatter)
    
    # Основной логгер
    logger.setLevel(logging.INFO)
    logger.addHandler(main_handler)
    
    # Создаем отдельные логгеры для разных типов событий
    relay_logger = logging.getLogger('relay')
    relay_logger.setLevel(logging.INFO)
    relay_logger.addHandler(relay_handler)
    
    card_logger = logging.getLogger('card')
    card_logger.setLevel(logging.INFO)
    card_logger.addHandler(card_handler)
    
    return relay_logger, card_logger

# Создаем дополнительные логгеры
relay_logger, card_logger = setup_logging()


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


def init_relay_controllers():
    global relay1_controller, relay2_controller
    
    logger.info("Инициализация контроллеров реле...")
    
    # адреса контроллеров
    relay1_controller = RelayController(0x38)  # PCA1
    relay2_controller = RelayController(0x39)  # PCA2

    # Маппинг для PCA1 (0x38)
    relay_logger.info("Настройка PCA1 (0x38):")
    relay1_controller.set_bit(0)  # Открыть замок (K:IN1)
    relay_logger.info("- Бит 0: Открыть замок (K:IN1)")
    relay1_controller.set_bit(1)  # Закрыть замок (K:IN2)
    relay_logger.info("- Бит 1: Закрыть замок (K:IN2)")
    relay1_controller.clear_bit(2)  # Зеленый светодиод (X:7)
    relay_logger.info("- Бит 2: Зеленый светодиод (X:7)")
    relay1_controller.clear_bit(3)  # Синий светодиод (X:8)
    relay_logger.info("- Бит 3: Синий светодиод (X:8)")
    relay1_controller.clear_bit(4)  # Красный светодиод (X:9)
    relay_logger.info("- Бит 4: Красный светодиод (X:9)")
    relay1_controller.set_bit(5)  # Группа - R2 (силовое реле) (KG0)
    relay_logger.info("- Бит 5: Группа - R2 (силовое реле) (KG0)")

    # Маппинг для PCA2 (0x39)
    relay_logger.info("Настройка PCA2 (0x39):")
    relay2_controller.set_bit(0)  # Аварийное освещение (KG1:IN1)
    relay_logger.info("- Бит 0: Аварийное освещение (KG1:IN1)")
    relay2_controller.set_bit(1)  # Группа - R3 (свет) (KG1:IN2)
    relay_logger.info("- Бит 1: Группа - R3 (свет) (KG1:IN2)")
    relay2_controller.set_bit(2)  # Соленоиды (KG1:IN3)
    relay_logger.info("- Бит 2: Соленоиды (KG1:IN3)")
    relay2_controller.set_bit(4)  # Радиатор1 (KG2:IN1)
    relay_logger.info("- Бит 4: Радиатор1 (KG2:IN1)")
    relay2_controller.set_bit(5)  # Свет спальня1 (KG2:IN2)
    relay_logger.info("- Бит 5: Свет спальня1 (KG2:IN2)")
    relay2_controller.set_bit(6)  # Бра левый1 (KG2:IN3)
    relay_logger.info("- Бит 6: Бра левый1 (KG2:IN3)")
    relay2_controller.set_bit(7)  # Бра правый1 (KG2:IN4)
    relay_logger.info("- Бит 7: Бра правый1 (KG2:IN4)")

    data1 = bus.read_byte(0x38)
    data2 = bus.read_byte(0x39)
    logger.info(f"Начальное состояние контроллеров: PCA1={bin(data1)}, PCA2={bin(data2)}")




active_cards = {}
logs = {}
active_key = None

GPIO.setmode(GPIO.BCM)

close_door_from_inside_counter = 1
open_door_counter = 1


class ProgramKilled(Exception):
    #logger.info("Error for some reason Exception")
    pass


def f_lock_door_from_inside(self):
    # logger.info(f"OFFF {bool(room_controller[23].state)}")
    logger.info("Lock door from inside")
    if bool(room_controller[23].state):
        relay2_controller.clear_bit(6)  # 6


# GPIO_23 callback (проверка сработки внут защелки (ригеля) на закрытие)
def f_lock_door_from_inside_thread():
    logger.info("Lock door from inside thread")
    while not bool(room_controller[23].state):
        relay1_controller.set_bit(4)  # Красный светодиод (X:9)
        time.sleep(0.2)
        relay1_controller.clear_bit(4)  # Красный светодиод (X:9)
        time.sleep(0.2)


def f_open_door_indicates_thread():
    logger.info("Open door indicates thread")
    for i in range(12):
        relay1_controller.set_bit(2)  # Зеленый светодиод (X:7)
        time.sleep(0.2)
        relay1_controller.clear_bit(2)  # Зеленый светодиод (X:7)
        time.sleep(0.2)


def f_before_lock_door_from_inside(self):
    logger.info("before lock door from inside")
    global close_door_from_inside
    time.sleep(0.01)
    thread_time = threading.Thread(target=f_lock_door_from_inside_thread)
    thread_time.start()
    if self.state:
        logger.info("Turn off red light")
        thread_time.join()
        relay1_controller.clear_bit(4)   # тушим красный светодиод


# GPIO_24 callback (проверка сработки "язычка" на открытие)
def f_lock_latch(self):
    time.sleep(1)
    logger.info("Lock latch")
    # close_door()


# GPIO_18 callback (использование ключа)
def f_using_key(self):
    logger.info("Use key")


# GPIO_10 callback (сейф)
def f_safe(self):
    logger.info("Safe")
    pass


# GPIO_25 callback датчик дыма 1
def f_fire_detector1(self):
    logger.info("Fire detector 1")
    pass


# GPIO_19 callback датчик дыма 2
def f_fire_detector2(self):
    logger.info("Fire detector 2")
    pass


# GPIO_26 callback датчик дыма 3
def f_fire_detector3(self):
    logger.info("Fire detector 3")
    pass


# GPIO_8 callback датчик дыма 4
def f_fire_detector4(self):
    logger.info("Fire detector 4")
    pass


def start_timer(func, type=1):
    global timer_thread, off_timer_thread
    logger.info(f"Start timer type {type}")
    # Создаем и запускаем поток для выполнения delayed_action через 30 минут
    if type == 1:

        delay_seconds = int(system_config.t1_timeout * 60)
        timer_thread = multiprocessing.Process(target=func, args=(delay_seconds, ))
        timer_thread.start()
    elif type == 2:
        delay_seconds = int(system_config.t2_timeout * 60)
        off_timer_thread = multiprocessing.Process(target=func, args=(delay_seconds, ))
        off_timer_thread.start()

def timer_turn_everything_off(time_seconds):
    logger.info("Timer for turn off")
    time.sleep(time_seconds)
    turn_everything_off()


def turn_on(type = 1):
    global lighting_bl, lighting_br, lighting_main
    logger.info("Turn everything on")
    relay1_controller.clear_bit(5)  # Соленоиды (KG1:IN3)
    relay2_controller.clear_bit(2)  # Группа - R2 (KG0)
    relay2_controller.clear_bit(1)  # Группа - R3 (свет) (KG1:IN2)
    #if type == 1:
    #   start_timer(timer_turn_everything_off)


# GPIO_22 callback картоприемник
def f_card_key(self):
    global active_key, is_sold
    card_logger.info("Сработал картоприемник")
    
    if active_key:
        try:
            card_role = get_card_role(active_key)
            card_logger.info(f"Роль карты: {card_role}")
            
            if card_role:
                logger.info(f"Включение устройств для роли: {card_role}")
                turn_on()
            else:
                logger.info("Роль карты не определена")
        except Exception as e:
            logger.error(f"Ошибка при обработке карты: {str(e)}")
    # else:
    #     print("Выключение")
    #     turn_on(type=2)



# GPIO_27 callback цепь автоматов
def f_circuit_breaker(self):
    logger.info("Curcuit breaker")
    pass


# GPIO_17 callback контроль наличия питания R3 (освещения)
def f_energy_sensor(self):
    logger.info("Energy sensor work")


# GPIO_20 callback окно1 (балкон)
def f_window1(self):
    logger.info("window 1")


# GPIO_07 callback окно2
def f_window2(self):
    logger.info("window 2")


# GPIO_13 callback окно3
def f_window3(self):
    logger.info("window 3")


# GPIO_16 callback выключатель основного света спальня1
def f_switch_main(self):
    global lighting_main
    logger.info(f"Switch main {lighting_main}")
    if not lighting_main:
        relay2_controller.clear_bit(5)  # Свет спальня1 (KG2:IN2)
        lighting_main = True
    else:
        relay2_controller.set_bit(5)  # Свет спальня1 (KG2:IN2)
        lighting_main = False


# GPIO_12 callback выключатель бра левый спальня1
def f_switch_bl(self):
    global lighting_bl
    logger.info(f"switch bl {lighting_bl}")
    if not lighting_bl:
        relay2_controller.clear_bit(6)  # Бра левый1 (KG2:IN3)
        lighting_bl = True
    else:
        relay2_controller.set_bit(6)  # Бра левый1 (KG2:IN3)
        lighting_bl = False


# GPIO_01 callback выключатель бра правый спальня1
def f_switch_br(self):
    global lighting_br
    logger.info(f"Switch br {lighting_br}")
    if not lighting_br:
        relay2_controller.clear_bit(7)  # Бра правый1 (KG2:IN4)
        lighting_br = True
    else:
        relay2_controller.set_bit(7)  # Бра правый1 (KG2:IN4)
        lighting_br = False


# GPIO_21 callback датчик затопления ВЩ
def f_flooding_sensor(self):
    logger.info("flooding_sensor")
    pass


def is_door_locked_from_inside():
    global room_controller
    time.sleep(0.1)
    logger.info(f"Door is locked - {not bool(room_controller[23].state)}")
    return not bool(room_controller[23].state)


def cardreader_before(self):
    logger.info("Cardreader before")
    #print(f"Card Insert ?, {self.state} , {self.__dict__}")
    pass


def init_room():
    logger.info("Init room")
    pin_structure = {
        0: None,
        1: PinController(1, f_switch_br, react_on=GPIO.FALLING, bouncetime=500),
        # кнопка-выключатель бра правый спальня1,
        2: None,
        3: None,
        5: None,
        6: None,
        7: PinController(7, f_window2),  # (окно2)
        8: PinController(8, f_fire_detector4),  # датчик дыма 4,
        9: None,
        10: PinController(10, f_safe, react_on=GPIO.FALLING),  # (сейф),
        11: None,  # кнопка-выключатель бра правый спальня2,
        12: PinController(12, f_switch_bl, react_on=GPIO.FALLING, bouncetime=500),
        # кнопка-выключатель бра левый спальня1
        13: PinController(13, f_window3),  # (окно3)
        14: None,
        15: None,
        16: PinController(16, f_switch_main, react_on=GPIO.FALLING, bouncetime=500),
        # кнопка-выключатель основного света спальня1
        17: PinController(17, f_energy_sensor, up_down=GPIO.PUD_DOWN, react_on=GPIO.RISING),
        # (контроль наличия питания R3 (освещения))
        18: PinController(18, f_using_key),  # (открытие замка механическим ключем)
        19: PinController(19, f_fire_detector2),  # (датчик дыма 2)
        20: PinController(20, f_window1),  # (окно1-балкон)
        21: PinController(21, f_flooding_sensor),  # (датчик затопления ВЩ)
        22: PinController(22, f_card_key, react_on=GPIO.FALLING, up_down=GPIO.PUD_UP, before_callback=cardreader_before),  # картоприемник
        23: PinController(23, f_lock_door_from_inside, before_callback=f_before_lock_door_from_inside),
        # замок "запрет"
        24: PinController(24, f_lock_latch),  # замок сработка "язычка"
        25: PinController(25, f_fire_detector1),  # датчик дыма 1
        26: PinController(26, f_fire_detector3),  # датчик дыма 3
        27: PinController(27, f_circuit_breaker, up_down=GPIO.PUD_DOWN, react_on=GPIO.RISING),
        # (цепь допконтактов автоматов)
    }

    global bus
    logger.info("The room has been initiated")
    return pin_structure


def get_card_role(card):
    global active_cards
    # TODO Change index
    # logger.info("Card role")
    if card:
        try:
            tip_index = int(card[5])
            #logger.info(f"role {tip_index}")
        except:
            tip_index = 26
            #logger.info(f"role except {tip_index}")

        if 0 <= tip_index <= 1:
            #logger.info("User")
            return "User"

        elif 2 <= tip_index <= 8:
            #logger.info("Worker")
            return "Worker"
        elif tip_index == 9:
            #logger.info("Admin")
            return "Admin"
        else:
            #logger.info("None User")
            return None
    else:
        return None



def second_light_control():
    logger.info("Start timer type 3")
    relay2_controller.clear_bit(0)  # Аварийное освещение (KG1:IN1)
    time.sleep(system_config.t3_timeout)
    relay2_controller.set_bit(0)  # Аварийное освещение (KG1:IN1)


# открытие замка с предварительной проверкой положения pin23(защелка, запрет) и последующим закрытием по таймауту
@retry(tries=10, delay=1)
def permit_open_door():
    global door_just_closed, can_open_the_door, active_key, second_light_thread
    card_role = get_card_role(active_key)
    logger.info(f"Card role after all: {card_role}")
    if is_door_locked_from_inside() and card_role != "Admin":
        logger.info("The door has been locked by the guest.")
        for i in range(10):
            relay1_controller.set_bit(2)  # Зеленый светодиод (X:7)
            time.sleep(0.2)
            relay1_controller.clear_bit(2)  # Зеленый светодиод (X:7)
            time.sleep(0.2)
    else:
        logger.info("Can open the door")
        can_open_the_door = True
        thread_time = threading.Thread(target=f_open_door_indicates_thread)
        thread_time.start()

        relay1_controller.clear_bit(1)  # Закрыть замок (K:IN2)
        time.sleep(0.115)
        relay1_controller.set_bit(1)  # Закрыть замок (K:IN2)
        #second_light_thread = multiprocessing.Process(target=second_light_control)
        #second_light_thread.start()
        time.sleep(4.25)
        close_door(thread_time)


# закрытие замка, с предварительной проверкой
@retry(tries=10, delay=1)
def close_door(thread_time=None):
    global door_just_closed, can_open_the_door
    if not can_open_the_door:
        logger.info("Door is closed. Permission denied!")  # ????
        return
    can_open_the_door = False
    door_just_closed = True
    time.sleep(0.1)
    relay1_controller.clear_bit(0)  # Открыть замок (K:IN1)
    time.sleep(0.115)
    relay1_controller.set_bit(0)  # Открыть замок (K:IN1)
    if thread_time:
        thread_time.join()
    #relay1_controller.clear_bit(2)  # Зеленый светодиод (X:7)
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
    logger.info("Turn everything off !")
    relay2_controller.set_bit(2)  # Соленоиды (KG1:IN3)
    if not is_sold:
        relay1_controller.set_bit(5)  # Группа - R2 (KG0)
    relay2_controller.set_bit(1)  # Группа - R3 (свет) (KG1:IN2)
    relay2_controller.set_bit(6)  # Бра левый1 (KG2:IN3)
    relay2_controller.set_bit(7)  # Бра правый1 (KG2:IN4)
    lighting_br = False
    lighting_bl = False
    lighting_main = False
    relay2_controller.set_bit(5)  # Свет спальня1 (KG2:IN2)
    relay2_controller.set_bit(4)  

@retry(tries=3, delay=1)
def get_active_cards():
    global active_cards, count_keys, is_sold, prev_is_sold
    cursor = get_db_connection().cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sql = "SELECT * FROM table_kluch WHERE dstart <= '{now}' AND dend >= '{now}' AND num = {" \
          "room_number} and tip IS NOT NULL AND tip >= 0 AND tip <= 9 ".format(now=now, room_number=system_config.room_number)
    cursor.execute(sql)
    key_list = cursor.fetchall()


    # key_list = [(301, '3D 00 4B 90 5E                  ', datetime.datetime(2017, 6, 7, 21, 0), datetime.datetime(2299, 1, 1, 0, 0), True, 9, datetime.datetime(2021, 2, 18, 14, 33, 25), None, 1), (301, '3D 00 4B 90 5E                  ', datetime.datetime(2017, 6, 7, 21, 0), datetime.datetime(2299, 1, 1, 0, 0), True, 9, datetime.datetime(2021, 8, 24, 10, 43, 18), None, 1), (301, '3D 00 4B 90 5E                  ', datetime.datetime(2017, 6, 7, 21, 0), datetime.datetime(2299, 1, 1, 0, 0), True, 9, datetime.datetime(2021, 8, 24, 10, 43, 22), None, 1), (301, '3D 00 4B 90 5E                  ', datetime.datetime(2017, 6, 7, 21, 0), datetime.datetime(2299, 1, 1, 0, 0), True, 9, datetime.datetime(2021, 8, 24, 12, 16, 44), None, 1), (301, '3D 00 4B 90 5E                  ', datetime.datetime(2017, 6, 7, 21, 0), datetime.datetime(2299, 1, 1, 0, 0), True, 9, datetime.datetime(2021, 8, 24, 11, 55, 42), None, 1), (301, '3D 00 4B 90 5E                  ', datetime.datetime(2017, 6, 7, 21, 0), datetime.datetime(2299, 1, 1, 0, 0), True, 9, datetime.datetime(2023, 5, 24, 14, 31, 51), None, 1), (301, '3D 00 4B 90 5E                  ', datetime.datetime(2017, 6, 7, 21, 0), datetime.datetime(2299, 1, 1, 0, 0), True, 9, datetime.datetime(2023, 5, 24, 14, 31, 53), None, 1), (301, '21 00 36 BD A2                  ', datetime.datetime(2023, 6, 6, 21, 0), datetime.datetime(2025, 6, 19, 0, 0), True, 26, datetime.datetime(2023, 6, 30, 13, 9, 57), None, 1), (301, '21 00 37 C9 F5                  ', datetime.datetime(2023, 7, 31, 21, 0), datetime.datetime(2024, 8, 3, 0, 0), True, 3, datetime.datetime(2023, 8, 3, 11, 51, 44), None, 1), (301, '21 00 37 C9 F5                  ', datetime.datetime(2023, 7, 31, 21, 0), datetime.datetime(2024, 8, 3, 0, 0), True, 3, datetime.datetime(2023, 8, 3, 11, 51, 47), None, 1), (301, '21 00 37 C9 F5                  ', datetime.datetime(2023, 7, 31, 21, 0), datetime.datetime(2024, 8, 3, 0, 0), True, 0, datetime.datetime(2023, 8, 3, 11, 48, 27), None, 1), (301, '21 00 37 C9 F5                  ', datetime.datetime(2023, 7, 31, 21, 0), datetime.datetime(2024, 8, 3, 0, 0), True, 2, datetime.datetime(2023, 8, 3, 11, 48, 50), None, 1)]
    active_cards = {handle_table_row(key): key for key in key_list}



    # sql_update = "UPDATE table_kluch SET tip = 1 WHERE dstart <= '{now}' AND dend >= '{now}' AND num = {" \
    #              "room_number} AND kl = '000037E663'".format(now=now, room_number=system_config.room_number)
    # cursor.execute(sql_update)
    # get_db_connection().commit()



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
        #logger.info(f"is_sold {is_sold}")
        if prev_is_sold != is_sold:
            if not is_sold:
                print("Is sold check !!!")
                #turn_everything_off()
            else:
                relay1_controller.clear_bit(4)  # R2
            prev_is_sold = is_sold



@retry(tries=10, delay=1)
def wait_rfid():
    logger.info("Ожидание карты RFID...")
    rfid_port = serial.Serial('/dev/ttyS0', 9600, timeout=1)
    read_byte = rfid_port.read(system_config.rfid_key_length)[0:10]
    key_ = read_byte.decode("utf-8")
    rfid_port.close()
    if key_:
        card_logger.info(f"Карта обнаружена: {key_} в {datetime.utcnow()}")
        return key_
    else:
        logger.warning("Карта не считана корректно")
        return None


@retry(tries=3, delay=5)
def check_pins():
    global room_controller
    pin_list_for_check = [1, 7, 8, 10, 12, 13, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27]
    for item in pin_list_for_check:
        room_controller[item].check_pin()
    state_message = "Pin state : "
    for item in pin_list_for_check:
        state_message += "pin#{pin}:{state}, ".format(pin=room_controller[item].pin, state=room_controller[item].state)
    logger.info(f"State: {state_message}")


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
templates = Jinja2Templates(directory="/home/pi/third_rooms/templates")

app.mount("/static", StaticFiles(directory="/home/pi/third_rooms/static"), name="static")


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
    log_file = 'debug.log'  # Укажите имя вашего файла с логами
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
    card_present = not GPIO.input(22)
    #print("Карта GPIO ",  card_present)
    data1 = bus.read_byte(0x38)
    data2 = bus.read_byte(0x39)

    card_logger.debug(f"Состояние контроллеров: PCA1={bin(data1)}, PCA2={bin(data2)}")
    card_logger.debug(f"Состояние реле1: {bin(relay1_controller.get_state())}")
    card_logger.debug(f"Состояние реле2: {bin(relay2_controller.get_state())}")
    if card_present:
        #print("Карта обнаружена")
        is_empty = False
        # if prev_card_present != card_present:
        #         #     prev_card_present = card_present
        #         # if off_timer_thread:
        #         #     off_timer_thread.terminate()
        #         #     logger.info("Stop timer type 2")
        #         #     off_timer_thread = None
        #         # if second_light_thread:
        #         #     second_light_thread.terminate()
        #         #     logger.info("Stop timer type 3")
        #         #     second_light_thread = None
    else:
        pass
        # if timer_thread:
        #     timer_thread.terminate()
        #     logger.info("Stop timer type 1")
        #     timer_thread = None
        #print("Карта не обнаружена")
        # is_empty = True
        # if prev_card_present != card_present:
        #     #start_timer(timer_turn_everything_off, 2)
        #     prev_card_present = card_present





def main():
    global room_controller, door_just_closed, active_key
    
    try:
        logger.info("=== ЗАПУСК СИСТЕМЫ УПРАВЛЕНИЯ КОМНАТОЙ ===")
        logger.info(f"Номер комнаты: {system_config.room_number}")
        
        # Инициализация контроллеров реле
        init_relay_controllers()
        
        # Получение активных карт
        logger.info("Получение списка активных карт...")
        get_active_cards()
        logger.info(f"Найдено активных карт: {len(active_cards)}")
        
        # Запуск задачи проверки новых карт
        logger.info(f"Запуск задачи проверки новых карт (интервал: {system_config.new_key_check_interval} сек)...")
        card_task = CheckActiveCardsTask(interval=timedelta(seconds=system_config.new_key_check_interval),
                                         execute=get_active_cards)
        card_task.start()
        logger.info("Задача проверки новых карт запущена")
        
        # Инициализация контроллеров пинов
        logger.info("Инициализация пинов комнаты...")
        room_controller = init_room()
        logger.info("Пины комнаты инициализированы")
        
        # Проверка статуса пинов
        check_pins()
        logger.info(f"Запуск задачи проверки пинов (интервал: {system_config.check_pin_timeout} сек)...")
        check_pin_task = CheckPinTask(interval=timedelta(seconds=system_config.check_pin_timeout), execute=check_pins)
        check_pin_task.start()
        logger.info("Задача проверки пинов запущена")
        
        # Запуск задачи проверки картоприемника
        logger.info("Запуск задачи проверки картоприемника (интервал: 4 сек)...")
        cardreader_find()
        cardreader_task = CheckCardTask(interval=timedelta(seconds=4), execute=cardreader_find)
        cardreader_task.start()
        logger.info("Задача проверки картоприемника запущена")
        
        # Включаем устройства
        logger.info("Включение устройств по умолчанию...")
        turn_on()
        logger.info("Устройства включены")
        
        logger.info("=== СИСТЕМА ГОТОВА К РАБОТЕ ===")
        
        # Основной цикл
        while True:
            logger.info("Ожидание ключа...")
            door_just_closed = False
            
            entered_key = wait_rfid()
            if entered_key:
                if entered_key in list(active_cards.keys()):
                    active_key = active_cards[entered_key]
                    card_role = get_card_role(active_key)
                    logger.info(f"Обнаружен корректный ключ, роль: {card_role} {entered_key}")
                    logger.info("Открытие двери...")
                    permit_open_door()
                else:
                    logger.warning(f"Обнаружен неизвестный ключ: {entered_key}")
                    logger.info("Сигнализация о неизвестном ключе...")
                    for i in range(15):
                        relay1_controller.set_bit(4)  # Красный светодиод (X:9)
                        time.sleep(0.1)
                        relay1_controller.clear_bit(4)  # Красный светодиод (X:9)
                        time.sleep(0.1)
            
    except ProgramKilled:
        logger.info("Получен сигнал завершения программы, очистка...")
        card_task.stop()
        check_pin_task.stop()
        cardreader_task.stop()
        logger.info("Задачи остановлены")
    except Exception as e:
        logger.error(f"Критическая ошибка в основном цикле: {str(e)}")


@app.on_event("startup")
async def on_startup():
    print("Starting server...")
    logging.basicConfig()
    print("Server started")

thread = threading.Thread(target=main)
thread.start()

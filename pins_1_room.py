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
import os

# Импорт обновленных контроллеров
from pin_controller import PinController
from relaycontroller import RelayController
from config import system_config, logger
from test import ProgramKilled

def setup_logging():
    """Настройка системы логирования с форматированием и ротацией файлов"""
    from logging.handlers import RotatingFileHandler
    
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
    main_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
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

# Глобальные переменные
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

# Глобальные контроллеры реле
relay1_controller = None  # PCA1
relay2_controller = None  # PCA2
relay3_controller = None  # PCA3 (новое реле)

def init_relay_controllers():
    global relay1_controller, relay2_controller, relay3_controller
    
    logger.info("Инициализация контроллеров реле...")
    
    # Адреса контроллеров
    relay1_controller = RelayController(0x38)  # PCA1
    relay2_controller = RelayController(0x39)  # PCA2
    relay3_controller = RelayController(0x40)  # PCA3 (новый контроллер)

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
    
    # Маппинг для PCA3 (0x40) - нового контроллера
    relay_logger.info("Настройка PCA3 (0x40):")
    relay3_controller.set_bit(0)  # Радиатор2 (KG3:IN1)
    relay_logger.info("- Бит 0: Радиатор2 (KG3:IN1)")
    relay3_controller.set_bit(1)  # Свет спальня2 (KG3:IN2)
    relay_logger.info("- Бит 1: Свет спальня2 (KG3:IN2)")
    relay3_controller.set_bit(2)  # Бра левый2 (KG3:IN3)
    relay_logger.info("- Бит 2: Бра левый2 (KG3:IN3)")
    relay3_controller.set_bit(3)  # Бра правый2 (KG3:IN4)
    relay_logger.info("- Бит 3: Бра правый2 (KG3:IN4)")

    data1 = bus.read_byte(0x38)
    data2 = bus.read_byte(0x39)
    data3 = bus.read_byte(0x40)
    logger.info(f"Начальное состояние контроллеров: PCA1={bin(data1)}, PCA2={bin(data2)}, PCA3={bin(data3)}")

# Остальные функции остаются такими же, как в вашем original файле...

# Функции обратного вызова для пинов

def f_lock_door_from_inside(self):
    logger.info("Lock door from inside")
    if bool(self.state):
        relay2_controller.clear_bit(6)  # 6

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

def f_lock_latch(self):
    time.sleep(1)
    logger.info("Lock latch")
    # close_door()

def f_using_key(self):
    logger.info("Use key")

def f_safe(self):
    logger.info("Safe")
    pass

def f_fire_detector1(self):
    logger.info("Fire detector 1")
    pass

def f_fire_detector2(self):
    logger.info("Fire detector 2")
    pass

def f_fire_detector3(self):
    logger.info("Fire detector 3")
    pass

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
    # Также включаем третий контроллер, если нужно

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

def f_circuit_breaker(self):
    logger.info("Curcuit breaker")
    pass

def f_energy_sensor(self):
    logger.info("Energy sensor work")

def f_window1(self):
    logger.info("window 1")

def f_window2(self):
    logger.info("window 2")

def f_window3(self):
    logger.info("window 3")

def f_switch_main(self):
    global lighting_main
    logger.info(f"Switch main {lighting_main}")
    if not lighting_main:
        relay2_controller.clear_bit(5)  # Свет спальня1 (KG2:IN2)
        lighting_main = True
    else:
        relay2_controller.set_bit(5)  # Свет спальня1 (KG2:IN2)
        lighting_main = False

def f_switch_bl(self):
    global lighting_bl
    logger.info(f"switch bl {lighting_bl}")
    if not lighting_bl:
        relay2_controller.clear_bit(6)  # Бра левый1 (KG2:IN3)
        lighting_bl = True
    else:
        relay2_controller.set_bit(6)  # Бра левый1 (KG2:IN3)
        lighting_bl = False

def f_switch_br(self):
    global lighting_br
    logger.info(f"Switch br {lighting_br}")
    if not lighting_br:
        relay2_controller.clear_bit(7)  # Бра правый1 (KG2:IN4)
        lighting_br = True
    else:
        relay2_controller.set_bit(7)  # Бра правый1 (KG2:IN4)
        lighting_br = False

# Добавляем обработчики для второй спальни и использования третьего реле
def f_switch_main2(self):
    global lighting_main2
    logger.info(f"Switch main2 {lighting_main2}")
    if not lighting_main2:
        relay3_controller.clear_bit(1)  # Свет спальня2 (KG3:IN2)
        lighting_main2 = True
    else:
        relay3_controller.set_bit(1)  # Свет спальня2 (KG3:IN2)
        lighting_main2 = False

def f_switch_bl2(self):
    global lighting_bl2
    logger.info(f"switch bl2 {lighting_bl2}")
    if not lighting_bl2:
        relay3_controller.clear_bit(2)  # Бра левый2 (KG3:IN3)
        lighting_bl2 = True
    else:
        relay3_controller.set_bit(2)  # Бра левый2 (KG3:IN3)
        lighting_bl2 = False

def f_switch_br2(self):
    global lighting_br2
    logger.info(f"Switch br2 {lighting_br2}")
    if not lighting_br2:
        relay3_controller.clear_bit(3)  # Бра правый2 (KG3:IN4)
        lighting_br2 = True
    else:
        relay3_controller.set_bit(3)  # Бра правый2 (KG3:IN4)
        lighting_br2 = False

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
    pass

def init_room():
    logger.info("Init room")
    pin_structure = {
        0: None,
        1: PinController(1, f_switch_br, up_down=GPIO.PUD_UP, react_on=GPIO.FALLING, bouncetime=0.5),
        # кнопка-выключатель бра правый спальня1
        2: PinController(2, f_switch_br2, up_down=GPIO.PUD_UP, react_on=GPIO.FALLING, bouncetime=0.5),
        # кнопка-выключатель бра правый спальня2
        3: PinController(3, f_switch_bl2, up_down=GPIO.PUD_UP, react_on=GPIO.FALLING, bouncetime=0.5),
        # кнопка-выключатель бра левый спальня2
        4: PinController(4, f_switch_main2, up_down=GPIO.PUD_UP, react_on=GPIO.FALLING, bouncetime=0.5),
        # кнопка-выключатель основного света спальня2
        5: None,
        6: None,
        7: PinController(7, f_window2),  # (окно2)
        8: PinController(8, f_fire_detector4),  # датчик дыма 4
        9: None,
        10: PinController(10, f_safe, up_down=GPIO.PUD_UP, react_on=GPIO.FALLING),  # (сейф)
        11: None,
        12: PinController(12, f_switch_bl, up_down=GPIO.PUD_UP, react_on=GPIO.FALLING, bouncetime=0.5),
        # кнопка-выключатель бра левый спальня1
        13: PinController(13, f_window3),  # (окно3)
        14: None,
        15: None,
        16: PinController(16, f_switch_main, up_down=GPIO.PUD_UP, react_on=GPIO.FALLING, bouncetime=0.5),
        # кнопка-выключатель основного света спальня1
        17: PinController(17, f_energy_sensor, up_down=GPIO.PUD_DOWN, react_on=GPIO.RISING),
        # (контроль наличия питания R3 (освещения))
        18: PinController(18, f_using_key),  # (открытие замка механическим ключем)
        19: PinController(19, f_fire_detector2),  # (датчик дыма 2)
        20: PinController(20, f_window1),  # (окно1-балкон)
        21: PinController(21, f_flooding_sensor),  # (датчик затопления ВЩ)
         22: PinController(22, f_card_key, up_down=GPIO.PUD_UP, react_on=GPIO.FALLING, before_callback=cardreader_before, bouncetime=0.3),  # картоприемник
        23: PinController(23, f_lock_door_from_inside, before_callback=f_before_lock_door_from_inside, bouncetime=0.3),
        # замок "запрет"
        24: PinController(24, f_lock_latch, bouncetime=0.3),  # замок сработка "язычка"
        25: PinController(25, f_fire_detector1),  # датчик дыма 1
        26: PinController(26, f_fire_detector3),  # датчик дыма 3
        27: PinController(27, f_circuit_breaker, up_down=GPIO.PUD_DOWN, react_on=GPIO.RISING),
        # (цепь допконтактов автоматов)
    }

    logger.info("Все пины комнаты успешно инициализированы")
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
        logger.info("Door is closed. Permission denied!")
        return
    can_open_the_door = False
    door_just_closed = True
    time.sleep(0.1)
    relay1_controller.clear_bit(0)  # Открыть замок (K:IN1)
    time.sleep(0.115)
    relay1_controller.set_bit(0)  # Открыть замок (K:IN1)
    if thread_time:
        thread_time.join()
    logger.info("Client has been entered!")


def handle_table_row(row_):
    return row_[system_config.rfig_key_table_index].replace(" ", "")


def get_db_connection():
    global db_connection
    if db_connection is None:
        db_connection = pymssql.connect(**system_config.db_config.__dict__)
    return db_connection


def turn_everything_off():
    global lighting_bl, lighting_br, lighting_main, lighting_bl2, lighting_br2, lighting_main2, is_sold
    logger.info("Turn everything off !")
    relay2_controller.set_bit(2)  # Соленоиды (KG1:IN3)
    if not is_sold:
        relay1_controller.set_bit(5)  # Группа - R2 (KG0)
    relay2_controller.set_bit(1)  # Группа - R3 (свет) (KG1:IN2)
    
    # Выключение света в спальне 1
    relay2_controller.set_bit(5)  # Свет спальня1 (KG2:IN2)
    relay2_controller.set_bit(6)  # Бра левый1 (KG2:IN3)
    relay2_controller.set_bit(7)  # Бра правый1 (KG2:IN4)
    lighting_main = False
    lighting_bl = False
    lighting_br = False
    
    # Выключение света в спальне 2 (третье реле)
    relay3_controller.set_bit(1)  # Свет спальня2 (KG3:IN2)
    relay3_controller.set_bit(2)  # Бра левый2 (KG3:IN3)
    relay3_controller.set_bit(3)  # Бра правый2 (KG3:IN4)
    lighting_main2 = False
    lighting_bl2 = False
    lighting_br2 = False
    
    # Выключение радиаторов
    relay2_controller.set_bit(4)  # Радиатор1 (KG2:IN1)
    relay3_controller.set_bit(0)  # Радиатор2 (KG3:IN1)


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
                logger.info(f"User key found: {key}")
                is_sold = True
                break
        
        if prev_is_sold != is_sold:
            if not is_sold:
                logger.info("Room is not sold anymore, turning everything off")
            else:
                relay1_controller.clear_bit(5)  # R2
            prev_is_sold = is_sold


@retry(tries=10, delay=1)
def wait_rfid():
    logger.info("Ожидание карты RFID...")
    try:
        # Увеличиваем таймаут
        rfid_port = serial.Serial('/dev/ttyS0', 9600, timeout=2)
        
        # Очищаем буфер перед чтением
        rfid_port.flushInput()
        
        # Получаем все доступные данные
        read_byte = rfid_port.read(system_config.rfid_key_length)
        
        # Декодируем только если данные не пустые
        if read_byte:
            key_ = read_byte.decode("utf-8")
            card_logger.info(f"Карта обнаружена: {key_} в {datetime.utcnow()}")
            rfid_port.close()
            return key_
        else:
            logger.debug("Карта не считана")
            rfid_port.close()
            return None
    except Exception as e:
        logger.error(f"Ошибка при чтении RFID: {str(e)}")
        try:
            rfid_port.close()
        except:
            pass
        return None


@retry(tries=3, delay=5)
def check_pins():
    global room_controller
    pin_list_for_check = [1, 2, 3, 4, 7, 8, 10, 12, 13, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27]
    for item in pin_list_for_check:
        if item in room_controller and room_controller[item] is not None:
            room_controller[item].check_pin()
    
    state_message = "Pin state : "
    for item in pin_list_for_check:
        if item in room_controller and room_controller[item] is not None:
            state_message += f"pin#{room_controller[item].pin}:{room_controller[item].state}, "
    
    logger.debug(f"State: {state_message}")


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


# Web-интерфейс для управления и отладки
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
    for i in range(28):
        if i in room_controller and room_controller[i] is not None:
            states.append({"pin" + str(i): f"state = {bool(room_controller[i].state)}"})
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


@app.get('/relay_state/')
async def get_relay_state():
    global relay1_controller, relay2_controller, relay3_controller
    states = {
        "PCA1 (0x38)": f"{bin(relay1_controller.get_state())}",
        "PCA2 (0x39)": f"{bin(relay2_controller.get_state())}",
        "PCA3 (0x40)": f"{bin(relay3_controller.get_state())}"
    }
    return states


@app.get('/toggle_relay/{controller}/{bit}')
async def toggle_relay(controller: int, bit: int):
    global relay1_controller, relay2_controller, relay3_controller
    
    if controller == 1:
        relay_controller = relay1_controller
        address = "0x38"
    elif controller == 2:
        relay_controller = relay2_controller
        address = "0x39"
    elif controller == 3:
        relay_controller = relay3_controller
        address = "0x40"
    else:
        return {"error": f"Invalid controller: {controller}"}
    
    if 0 <= bit <= 7:
        relay_controller.toggle_bit(bit)
        return {"success": f"Toggled bit {bit} on controller {address}"}
    else:
        return {"error": f"Invalid bit: {bit}"}


prev_card_present = True
def cardreader_find():
    global is_empty, timer_thread, off_timer_thread, prev_card_present, second_light_thread
    try:
        card_present = not GPIO.input(22)
        data1 = bus.read_byte(0x38)
        data2 = bus.read_byte(0x39)
        data3 = bus.read_byte(0x40)

        card_logger.debug(f"Состояние контроллеров: PCA1={bin(data1)}, PCA2={bin(data2)}, PCA3={bin(data3)}")
        card_logger.debug(f"Состояние реле1: {bin(relay1_controller.get_state())}")
        card_logger.debug(f"Состояние реле2: {bin(relay2_controller.get_state())}")
        card_logger.debug(f"Состояние реле3: {bin(relay3_controller.get_state())}")
        
        if card_present:
            is_empty = False
            # Дополнительная логика по необходимости
        else:
            # Логика для случая отсутствия карты
            pass
    except Exception as e:
        logger.error(f"Ошибка при проверке картоприемника: {str(e)}")


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
        # При критической ошибке, пытаемся освободить ресурсы
        try:
            GPIO.cleanup()
        except:
            pass


@app.on_event("startup")
async def on_startup():
    print("Starting server...")
    logging.basicConfig()
    print("Server started")


# Запуск основного приложения в отдельном потоке
thread = threading.Thread(target=main)
thread.daemon = True
thread.start()

# Если запускаем скрипт напрямую
if __name__ == "__main__":
    # Регистрация обработчика сигналов для корректного завершения
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        # Запускаем основной поток, если он еще не запущен
        if not thread.is_alive():
            thread.start()
        
        # Держим основной поток активным
        while True:
            time.sleep(1)
    except ProgramKilled:
        print("Program killed: running cleanup code")
        # Дополнительная очистка ресурсов
        GPIO.cleanup()
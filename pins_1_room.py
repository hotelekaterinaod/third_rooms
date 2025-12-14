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
gpio_locked = False

db_connection = None

bus = smbus.SMBus(1)


# Класс для обработки RFID считывателя
class RFIDHandler:
    """
    Обработчик RFID-считывателя в неблокирующем режиме
    """
    def __init__(self, port='/dev/ttyS0', baudrate=9600, key_length=None):
        self.port = port
        self.baudrate = baudrate
        self.key_length = key_length
        self.serial_port = None
        self.callback = None
        self.running = False
        self.thread = None
        self._last_key = None
        self._last_key_time = None
        self._lock = threading.Lock()
        
    def start(self, callback=None):
        """
        Запуск обработчика RFID
        
        Args:
            callback: функция, которая будет вызвана при получении ключа
        """
        if self.running:
            return
            
        self.callback = callback
        self.running = True
        self.thread = threading.Thread(target=self._reader_loop)
        self.thread.daemon = False  # Изменено с daemon=True на False
        self.thread.start()
        
    def stop(self):
        """
        Остановка обработчика RFID
        """
        with self._lock:
            self.running = False
            
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)  # Увеличен таймаут
            self.thread = None
            
        if self.serial_port:
            try:
                self.serial_port.close()
            except:
                pass
            self.serial_port = None
    
    def _reader_loop(self):
        """
        Внутренний цикл чтения из последовательного порта
        """
        import serial
        
        try:
            self.serial_port = serial.Serial(
                self.port, 
                baudrate=self.baudrate,
                timeout=0.1  # Короткий таймаут для неблокирующей работы
            )
            
            # Очистка буфера
            self.serial_port.flushInput()
            
            buffer = bytearray()
            
            while True:
                # Проверка флага остановки в безопасном контексте
                with self._lock:
                    if not self.running:
                        break
                
                # Чтение доступных данных (неблокирующее)
                if self.serial_port and self.serial_port.in_waiting > 0:
                    data = self.serial_port.read(self.serial_port.in_waiting)
                    buffer.extend(data)
                    
                    # Проверяем, накопили ли мы полный ключ
                    if self.key_length is not None and len(buffer) >= self.key_length:
                        # Берем последние key_length байт
                        key_data = buffer[-self.key_length:]
                        buffer.clear()
                        
                        try:
                            key = key_data.decode('utf-8')
                            
                            # Предотвращаем повторное считывание одной и той же карты
                            now = datetime.now()
                            if (self._last_key != key or 
                                self._last_key_time is None or 
                                (now - self._last_key_time).total_seconds() > 1.0):
                                self._last_key = key
                                self._last_key_time = now
                                
                                # Безопасный вызов callback
                                local_callback = None
                                with self._lock:
                                    if self.running and self.callback:
                                        local_callback = self.callback
                                
                                if local_callback:
                                    # Вызываем напрямую, без создания нового потока
                                    try:
                                        local_callback(key)
                                    except Exception as e:
                                        # Безопасная обработка ошибок колбэка
                                        print(f"Error in RFID callback: {str(e)}")
                        except Exception as e:
                            print(f"Error decoding RFID key: {str(e)}")
                else:
                    # Небольшая пауза, чтобы не грузить CPU
                    time.sleep(0.01)
                    
        except Exception as e:
            print(f"Error in RFID reader: {str(e)}")
        finally:
            if self.serial_port:
                try:
                    self.serial_port.close()
                except:
                    pass
                self.serial_port = None
                
    def read_key_once(self, timeout=2.0):
        """
        Синхронное чтение ключа (блокирующий вызов)
        
        Args:
            timeout: таймаут ожидания в секундах
            
        Returns:
            str: считанный ключ или None, если таймаут
        """
        import serial
        
        try:
            with serial.Serial(self.port, baudrate=self.baudrate, timeout=timeout) as port:
                port.flushInput()
                
                if self.key_length is not None:
                    data = port.read(self.key_length)
                else:
                    data = port.readline()
                    
                if data:
                    return data.decode('utf-8')
                else:
                    return None
        except Exception as e:
            logger.error(f"Error reading RFID key: {str(e)}")
            return None


def init_relay_controllers():
    global relay1_controller, relay2_controller, relay3_controller
    
    logger.info("Инициализация контроллеров реле...")
    
    # адреса контроллеров
    relay1_controller = RelayController(0x38)  # PCA1
    relay2_controller = RelayController(0x39)  # PCA2
    
    # Пробуем инициализировать реле 3, но продолжаем даже если его нет
    try:
        relay3_controller = RelayController(0x3B)  # PCA3
        has_relay3 = relay3_controller.device_available
        logger.info(f"relay3_controller 3 status: {has_relay3}")
    except Exception as e:
        logger.warning(f"Не удалось инициализировать реле 3: {str(e)}")
        relay3_controller = None
        has_relay3 = False
    
    # Сбрасываем все контроллеры (все биты в 1)
    logger.info("Сброс всех контроллеров реле...")
    
    relay1_controller.reset_all()
    relay2_controller.reset_all()
    if has_relay3 and relay3_controller:
        relay3_controller.reset_all()
    
    # Настраиваем начальное состояние контроллеров
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
    
    # Инициализация третьего реле, если оно доступно
    if has_relay3 and relay3_controller:
        relay_logger.info("Настройка PCA3 (0x3B):")
        relay3_controller.set_bit(4)  # Инициализация реле 3, бит 0
        relay_logger.info("- Бит 0: Инициализирован")
        relay3_controller.set_bit(5)  # Инициализация реле 3, бит 1
        relay_logger.info("- Бит 1: Инициализирован")
        relay3_controller.set_bit(6)  # Инициализация реле 3, бит 2
        relay_logger.info("- Бит 2: Инициализирован")
        relay3_controller.set_bit(7)  # Инициализация реле 3, бит 3
        relay_logger.info("- Бит 3: Инициализирован")

    # Выводим начальное состояние контроллеров
    data1 = relay1_controller.get_state()
    data2 = relay2_controller.get_state()
    if has_relay3 and relay3_controller:
        data3 = relay3_controller.get_state()
        logger.info(f"Начальное состояние контроллеров: PCA1={bin(data1)}, PCA2={bin(data2)}, PCA3={bin(data3)}")
    else:
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
    if gpio_locked:
        return
    time.sleep(1)
    logger.info("Lock latch")
    # close_door()


# GPIO_18 callback (использование ключа)
def f_using_key(self):
    if gpio_locked:
        return
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



def rfid_thread_function():
    """
    Функция для чтения RFID-карт в отдельном потоке - максимально близка к оригинальному коду
    """
    global active_key
    
    while True:
        try:
            # Точно так же, как в оригинальном коде
            rfid_port  = serial.Serial('/dev/ttyS0', 9600, timeout=1)
            rfid_port.flushInput()
            
            # Чтение данных
            data = (rfid_port.read(system_config.rfid_key_length)[1:11])
            rfid_port.close()
            # Если данные получены
            if data:
                # Декодирование ключа
                key = data.decode('utf-8')
                
                # Логируем для отладки
                logger.info(f"RFID ключ считан: {key}")
                
                # ТОЧНО так же, как в оригинальном коде
                if key in active_cards:
                    # Если ключ найден, используем его
                    active_key = active_cards[key]
                    card_role = get_card_role(active_key)
                    logger.info(f"Ключ найден, роль: {card_role}")
                    permit_open_door()
                else:
                    # Если ключ не найден, сигнализируем красным светодиодом
                    logger.warning(f"Ключ не найден: {key}")
                    # Мигаем красным светодиодом
                    for i in range(15):
                        relay1_controller.set_bit(4)  # Красный светодиод
                        time.sleep(0.1)
                        relay1_controller.clear_bit(4)  # Красный светодиод
                        time.sleep(0.1)
                
            # Закрываем соединение
            
            
            # Небольшая пауза между чтениями
            time.sleep(0.1)
            
        except Exception as e:
            logger.error(f"Ошибка при чтении RFID: {str(e)}")
            time.sleep(1)  # Пауза при ошибке



def turn_on(type = 1):
    global lighting_bl, lighting_br, lighting_main, gpio_locked
    logger.info("Turn everything on")
    gpio_locked = True
    relay1_controller.clear_bit(5)
    time.sleep(0.5)
    relay2_controller.clear_bit(2)
    time.sleep(0.3)
    relay2_controller.clear_bit(1)
    time.sleep(0.5)
    gpio_locked = False
    logger.info("Turn everything on - complete")


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
    if gpio_locked:
        return
    logger.info("Curcuit breaker")
    pass


# GPIO_17 callback контроль наличия питания R3 (освещения)
def f_energy_sensor(self):
    if gpio_locked:
        return
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
        relay2_controller.clear_bit(5, debounce_ms=25)  # Свет спальня1 (KG2:IN2)
        lighting_main = True
    else:
        relay2_controller.set_bit(5, debounce_ms=25)  # Свет спальня1 (KG2:IN2)
        lighting_main = False

def f_switch_main_2(self):
    global lighting_main2
    logger.info(f"Switch main {lighting_main2}")
    if not lighting_main2:
        relay3_controller.clear_bit(5, debounce_ms=25)  # Свет спальня1 (KG2:IN2)
        lighting_main2 = True
    else:
        relay3_controller.set_bit(5, debounce_ms=25)  # Свет спальня1 (KG2:IN2)
        lighting_main2 = False


# GPIO_12 callback выключатель бра левый спальня1
def f_switch_bl(self):
    global lighting_bl
    logger.info(f"switch bl {lighting_bl}")
    if not lighting_bl:
        relay2_controller.clear_bit(6, debounce_ms=25)  # Бра левый1 (KG2:IN3)
        lighting_bl = True
    else:
        relay2_controller.set_bit(6, debounce_ms=25)  # Бра левый1 (KG2:IN3)
        lighting_bl = False


def f_switch_bl_2(self):
    global lighting_bl2
    logger.info(f"switch bl {lighting_bl2}")
    if not lighting_bl2:
        relay3_controller.clear_bit(6, debounce_ms=25)  # Бра левый1 (KG2:IN3)
        lighting_bl2 = True
    else:
        relay3_controller.set_bit(6, debounce_ms=25)  # Бра левый1 (KG2:IN3)
        lighting_bl2 = False


def f_switch_br_2(self):
    global lighting_br2
    logger.info(f"switch bl 2 {lighting_br2}")
    if not lighting_br2:
        relay3_controller.clear_bit(7, debounce_ms=25)  # Бра левый1 (KG2:IN3)
        lighting_br2 = True
    else:
        relay3_controller.set_bit(7, debounce_ms=25)  # Бра левый1 (KG2:IN3)
        lighting_br2 = False


# GPIO_01 callback выключатель бра правый спальня1
def f_switch_br(self):
    global lighting_br
    logger.info(f"Switch br {lighting_br}")
    if not lighting_br:
        relay2_controller.clear_bit(7, debounce_ms=25)  # Бра правый1 (KG2:IN4)
        lighting_br = True
    else:
        relay2_controller.set_bit(7, debounce_ms=25)  # Бра правый1 (KG2:IN4)
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
    global relay3_controller
    logger.info(f"Init room")
    pin_structure = {
        0: PinController(0, f_switch_br_2, react_on=GPIO.FALLING, bouncetime=80),
        1: PinController(1, f_switch_br, react_on=GPIO.FALLING, bouncetime=80),
        # кнопка-выключатель бра правый спальня1,
        2: None,
        3: None,
        5: PinController(5, f_switch_bl_2, react_on=GPIO.FALLING, bouncetime=80),
        6: PinController(6, f_switch_main_2, react_on=GPIO.FALLING, bouncetime=80),
        7: PinController(7, f_window2),  # (окно2)
        8: PinController(8, f_fire_detector4),  # датчик дыма 4,
        9: None,
        10: PinController(10, f_safe, react_on=GPIO.FALLING),  # (сейф),
        11: None,  # кнопка-выключатель бра правый спальня2,
        12: PinController(12, f_switch_bl, react_on=GPIO.FALLING, bouncetime=80),
        # кнопка-выключатель бра левый спальня1
        13: PinController(13, f_window3),  # (окно3)
        14: None,
        15: None,
        16: PinController(16, f_switch_main, react_on=GPIO.FALLING, bouncetime=80),
        # кнопка-выключатель основного света спальня1
        17: PinController(17, f_energy_sensor, up_down=GPIO.PUD_DOWN, react_on=GPIO.RISING, bouncetime=200),
        18: PinController(18, f_using_key, bouncetime=200),
        19: PinController(19, f_fire_detector2),  # (датчик дыма 2)
        20: PinController(20, f_window1),  # (окно1-балкон)
        21: PinController(21, f_flooding_sensor),  # (датчик затопления ВЩ)
        22: PinController(22, f_card_key, react_on=GPIO.FALLING, up_down=GPIO.PUD_UP, before_callback=cardreader_before),  # картоприемник
        23: PinController(23, f_lock_door_from_inside, before_callback=f_before_lock_door_from_inside, bouncetime=200),
        24: PinController(24, f_lock_latch, bouncetime=200),
        25: PinController(25, f_fire_detector1),  # датчик дыма 1
        26: PinController(26, f_fire_detector3),  # датчик дыма 3
        27: PinController(27, f_circuit_breaker, up_down=GPIO.PUD_DOWN, react_on=GPIO.RISING, bouncetime=200),
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
    
    if db_connection is not None:
        try:
            cursor = db_connection.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            return db_connection
        except:
            try:
                db_connection.close()
            except:
                pass
            db_connection = None
    
    try:
        config_dict = system_config.db_config.__dict__.copy()
        config_dict['timeout'] = 5
        config_dict['login_timeout'] = 3
        db_connection = pymssql.connect(**config_dict)
        logger.info("БД подключена")
        return db_connection
    except Exception as e:
        logger.error("Ошибка БД: {}".format(str(e)))
        db_connection = None
        raise



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
    """
    Получение активных карт с новой логикой отбора:
    
    1. Группируем ключи только по типу (tip: 0-9)
    2. Для каждого типа выбираем ключ с самой свежей датой tekdat
    3. Максимум может быть 10 активных ключей (по одному на каждый тип)
    4. Затем фильтруем по датам активности (dstart <= now <= dend)
    """
    global active_cards, count_keys, is_sold, prev_is_sold, db_connection
    
    try:
        cursor = get_db_connection().cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Получаем все записи ключей для комнаты (без фильтрации по датам)
        sql = """
        SELECT * FROM table_kluch 
        WHERE num = {room_number}
        """.format(room_number=system_config.room_number)
        logger.info(f"SQL запрос для получения всех ключей: {sql}")
        
        cursor.execute(sql)
        all_keys = cursor.fetchall()
        
        logger.info(f"Найдено всего записей ключей для комнаты {system_config.room_number}: {len(all_keys)}")
        logger.info("Применяем новую логику отбора: группировка по tip (0-9), выбор самых свежих по tekdat")
        
        # Группируем ключи только по tip, выбираем самые свежие по tekdat
        keys_by_tip = {}
        
        for key_row in all_keys:
            try:
                # Получаем id ключа (для логирования)
                key_id = handle_table_row(key_row)
                
                # Получаем tip (поле может быть пустым или содержать цифру 0-9)
                tip = key_row[5] if len(key_row) > 5 and key_row[5] is not None else 0
                if tip == '' or tip is None:
                    tip = 0
                try:
                    tip = int(tip)
                except (ValueError, TypeError):
                    tip = 0
                
                # Получаем tekdat (дата последнего изменения)
                tekdat = key_row[6] if len(key_row) > 6 and key_row[6] is not None else datetime.min
                
                # Группируем только по tip (максимум 10 типов: 0-9)
                # Если это первая запись для данного tip или текущая запись более свежая
                if tip not in keys_by_tip or tekdat > keys_by_tip[tip]['tekdat']:
                    keys_by_tip[tip] = {
                        'key_row': key_row,
                        'tekdat': tekdat,
                        'key_id': key_id,
                        'tip': tip
                    }
                    logger.debug(f"Обновлен актуальный ключ для tip {tip}: key_id={key_id}, tekdat={tekdat}")
                    
            except Exception as e:
                logger.error(f"Ошибка при обработке записи ключа: {str(e)}")
                continue
        
        logger.info(f"Найдено уникальных типов ключей (tip): {len(keys_by_tip)} из возможных 10 (0-9)")
        
        # Фильтруем по датам активности только самые свежие ключи для каждого типа
        active_key_list = []
        for tip, key_data in keys_by_tip.items():
            key_row = key_data['key_row']
            
            try:
                # Проверяем даты активности (правильная индексация)
                dstart = key_row[2] if len(key_row) > 2 else None
                dend = key_row[3] if len(key_row) > 3 else None
                
                # Добавляем отладочное логирование типов данных
                logger.debug(f"Отладка типов данных для ключа {key_data['key_id']}: dstart={dstart} (тип: {type(dstart)}), dend={dend} (тип: {type(dend)})")
                
                current_time = datetime.now()
                
                # Обработка dstart
                dstart_datetime = None
                if dstart is not None:
                    if isinstance(dstart, str):
                        try:
                            dstart_datetime = datetime.strptime(dstart, "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            logger.warning(f"Неверный формат dstart: {dstart}")
                            dstart_datetime = None
                    elif isinstance(dstart, datetime):
                        dstart_datetime = dstart
                    elif isinstance(dstart, bool):
                        # Если это bool, пропускаем проверку dstart
                        dstart_datetime = None
                    else:
                        logger.warning(f"Неизвестный тип dstart: {type(dstart)}, значение: {dstart}")
                        dstart_datetime = None
                
                # Обработка dend
                dend_datetime = None
                if dend is not None:
                    if isinstance(dend, str):
                        try:
                            dend_datetime = datetime.strptime(dend, "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            logger.warning(f"Неверный формат dend: {dend}")
                            dend_datetime = None
                    elif isinstance(dend, datetime):
                        dend_datetime = dend
                    elif isinstance(dend, bool):
                        # Если это bool, пропускаем проверку dend
                        dend_datetime = None
                    else:
                        logger.warning(f"Неизвестный тип dend: {type(dend)}, значение: {dend}")
                        dend_datetime = None
                
                # Проверяем, что ключ активен в текущее время
                start_valid = dstart_datetime is None or dstart_datetime <= current_time
                end_valid = dend_datetime is None or dend_datetime >= current_time
                
                if start_valid and end_valid:
                    active_key_list.append(key_row)
                    logger.debug(f"Ключ {key_data['key_id']} (tip: {key_data['tip']}) прошел проверку дат активности")
                else:
                    logger.debug(f"Ключ {key_data['key_id']} (tip: {key_data['tip']}) не прошел проверку дат: start_valid={start_valid}, end_valid={end_valid}")
                    
            except Exception as e:
                logger.error(f"Ошибка при проверке дат активности ключа {key_data.get('key_id', 'неизвестен')}: {str(e)}")
                continue
        
        logger.info(f"Найдено активных ключей после обработки: {len(active_key_list)}")
        
        # Логируем подробную информацию о каждом активном ключе
        if active_key_list:
            logger.info("=== АКТИВНЫЕ КЛЮЧИ С ПОЛНОЙ ИНФОРМАЦИЕЙ ===")
            logger.info(f"Всего активных типов ключей: {len(active_key_list)} из 10 возможных (tip: 0-9)")
            for i, key_row in enumerate(active_key_list):
                try:
                    key_id = handle_table_row(key_row)
                    tip = key_row[5] if len(key_row) > 5 and key_row[5] is not None else 0
                    if tip == '' or tip is None:
                        tip = 0
                    try:
                        tip = int(tip)
                    except (ValueError, TypeError):
                        tip = 0
                    
                    tekdat = key_row[6] if len(key_row) > 6 else 'Нет данных'
                    dstart = key_row[2] if len(key_row) > 2 else 'Нет данных'
                    dend = key_row[3] if len(key_row) > 3 else 'Нет данных'
                    
                    # Дополнительные поля из базы данных
                    num = key_row[0] if len(key_row) > 0 else 'Нет данных'
                    additional_info = f", поля БД: {len(key_row)} полей" if len(key_row) > 7 else ""
                    
                    logger.info(f"Ключ TIP #{tip}: ID={key_id}, TEKDAT={tekdat}, DSTART={dstart}, DEND={dend}, NUM={num}{additional_info}")
                    
                except Exception as e:
                    logger.error(f"Ошибка при логировании ключа #{i+1}: {str(e)}")
            logger.info("=== КОНЕЦ СПИСКА АКТИВНЫХ КЛЮЧЕЙ ===")
        else:
            logger.info("Активных ключей не найдено")
        
        # Создаем словарь ключей
        active_cards = {handle_table_row(key): key for key in active_key_list}
        
        keys_for_rpi_update = []
        for key_row in all_keys:
            try:
                rpi_val = key_row[8] if len(key_row) > 8 else None
                if rpi_val != 1:
                    num_val = key_row[0] if len(key_row) > 0 else None
                    id_val = key_row[1] if len(key_row) > 1 else None
                    if num_val is None or id_val is None:
                        logger.warning("Пропуск rpi update: отсутствует num или id (index0/index1)")
                        continue
                    keys_for_rpi_update.append((num_val, id_val))
            except Exception as e:
                logger.error("Ошибка анализа строки для rpi update: {err}".format(err=str(e)))
                continue

        if keys_for_rpi_update:
            logger.info("Будет обновлено rpi для {cnt} записей".format(cnt=len(keys_for_rpi_update)))
            sql_update = "UPDATE table_kluch SET rpi = 1 WHERE num = {room_number}".format(room_number=system_config.room_number)
            try:
                cursor.execute(sql_update)
                get_db_connection().commit()
                logger.info("Success update rpi for changed rows")
            except Exception as e:
                logger.error("Commit error after rpi bulk updates: {err}".format(err=str(e)))
        else:
            logger.debug("Нет строк для обновления rpi")

        # Сохраняем количество активных ключей (по типам) для диагностики
        count_keys = len(active_key_list)
        
        # Оригинальный код для проверки is_sold
        if active_key_list:
            is_sold = False
            for key in active_key_list:
                card_role = get_card_role(key)
                
                if card_role == "User":
                    logger.info(f"Найден пользователь: {key}")
                    is_sold = True
                    break
                    
            if prev_is_sold != is_sold:
                if not is_sold:
                    logger.info("Is sold check !!!")
                else:
                    relay1_controller.clear_bit(4)  # Очистка бита 4 на реле 1
                prev_is_sold = is_sold
        
                prev_is_sold = is_sold
        
    except Exception as e:
        logger.error(f"Ошибка получения карт: {str(e)}")
        db_connection = None
        
    return active_cards
def log_key_usage(key_row, match_type):
    """Функция для подробного логирования использования ключа при открытии двери"""
    try:
        # Получаем подробную информацию о ключе
        key_id = handle_table_row(key_row)
        tip = key_row[5] if len(key_row) > 5 and key_row[5] is not None else 0
        if tip == '' or tip is None:
            tip = 0
        try:
            tip = int(tip)
        except (ValueError, TypeError):
            tip = 0
        
        tekdat = key_row[6] if len(key_row) > 6 else 'Нет данных'
        dstart = key_row[2] if len(key_row) > 2 else 'Нет данных'
        dend = key_row[3] if len(key_row) > 3 else 'Нет данных'
        num = key_row[0] if len(key_row) > 0 else 'Нет данных'
        
        card_role = get_card_role(key_row)
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Дополнительная информация о всех полях ключа
        all_fields = ""
        for i, field in enumerate(key_row):
            all_fields += f"[{i}]={field}, "
        all_fields = all_fields.rstrip(", ")
        
        card_logger.info("=" * 60)
        card_logger.info("ДВЕРЬ ОТКРЫТА КЛЮЧОМ!")
        card_logger.info(f"Время открытия: {current_time}")
        card_logger.info(f"Способ распознавания: {match_type}")
        card_logger.info(f"ID ключа: {key_id}")
        card_logger.info(f"Тип ключа (TIP): {tip}")
        card_logger.info(f"Роль пользователя: {card_role}")
        card_logger.info(f"Номер комнаты: {num}")
        card_logger.info(f"Дата начала действия (DSTART): {dstart}")
        card_logger.info(f"Дата окончания действия (DEND): {dend}")
        card_logger.info(f"Дата последнего изменения (TEKDAT): {tekdat}")
        card_logger.info(f"Все поля БД: {all_fields}")
        card_logger.info("=" * 60)
        
    except Exception as e:
        card_logger.error(f"Ошибка при логировании использования ключа: {str(e)}")


# Обработчик ключа RFID - вызывается из RFIDHandler
def handle_rfid_key(key):
    global active_key
    if not key:
        logger.warning("Получен пустой ключ RFID")
        return
        
    # Выведем отладочную информацию
    card_logger.info(f"Карта обнаружена (raw): [{key}], длина: {len(key)}")
    
    # Очистим ключ от пробелов и других специальных символов
    cleaned_key = key.strip().replace(" ", "")
    card_logger.info(f"Очищенный ключ: [{cleaned_key}], длина: {len(cleaned_key)}")
    
    # Выведем список доступных ключей для отладки
    card_logger.info(f"Доступные ключи: {list(active_cards.keys())}")
    
    # Проверим ключ (точное совпадение и совпадение с очисткой)
    exact_match = key in list(active_cards.keys())
    cleaned_match = cleaned_key in list(active_cards.keys())
    card_logger.info(f"Exact match: {exact_match}, Cleaned match: {cleaned_match}")
    
    # Попробуем найти ключ, игнорируя пробелы, регистр и другие символы
    found_key = None
    for active_key_str in active_cards.keys():
        if active_key_str.strip().replace(" ", "") == cleaned_key:
            found_key = active_key_str
            break
    
    if found_key:
        active_key = active_cards[found_key]
        card_role = get_card_role(active_key)
        card_logger.info(f"Обнаружен корректный ключ (через гибкий поиск), роль: {card_role}, ключ: {found_key}")
        log_key_usage(active_key, "гибкий поиск")
        permit_open_door()
    elif exact_match:
        active_key = active_cards[key]
        card_role = get_card_role(active_key)
        card_logger.info(f"Обнаружен корректный ключ (точное совпадение), роль: {card_role}, ключ: {key}")
        log_key_usage(active_key, "точное совпадение")
        permit_open_door()
    elif cleaned_match:
        active_key = active_cards[cleaned_key]
        card_role = get_card_role(active_key)
        card_logger.info(f"Обнаружен корректный ключ (после очистки), роль: {card_role}, ключ: {cleaned_key}")
        log_key_usage(active_key, "после очистки")
        permit_open_door()
    else:
        card_logger.warning(f"Обнаружен неизвестный ключ: {key}")
        card_logger.info("Сигнализация о неизвестном ключе...")
        for i in range(15):
            relay1_controller.set_bit(4)  # Красный светодиод (X:9)
            time.sleep(0.1)
            relay1_controller.clear_bit(4)  # Красный светодиод (X:9)
            time.sleep(0.1)


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
        self.daemon = False  # Изменено с daemon=True на False
        self.stopped = threading.Event()
        self.interval = interval
        self.execute = execute

    def stop(self):
        self.stopped.set()
        self.join(timeout=2.0)  # Добавлен таймаут для безопасной остановки

    def run(self):
        while not self.stopped.wait(self.interval.total_seconds()):
            try:
                self.execute()
            except Exception as e:
                logger.error(f"Ошибка в задаче проверки пинов: {str(e)}")


class CheckActiveCardsTask(threading.Thread):
    def __init__(self, interval, execute, *args, **kwargs):
        threading.Thread.__init__(self)
        self.daemon = False  # Изменено с daemon=True на False
        self.stopped = threading.Event()
        self.interval = interval
        self.execute = execute
        self.args = args
        self.kwargs = kwargs

    def stop(self):
        self.stopped.set()
        self.join(timeout=2.0)  # Добавлен таймаут для безопасной остановки

    def run(self):
        while not self.stopped.wait(self.interval.total_seconds()):
            try:
                self.execute(*self.args, **self.kwargs)
            except Exception as e:
                logger.error(f"Ошибка в задаче проверки карт: {str(e)}")


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
    try:
        card_present = not GPIO.input(22)
        
        # Проверка состояния реле (для логгирования)
        try:
            data1 = relay1_controller.get_state()
            data2 = relay2_controller.get_state()
            if hasattr(relay3_controller, 'device_available') and relay3_controller.device_available:
                data3 = relay3_controller.get_state()
                card_logger.debug(f"Состояние контроллеров: PCA1={bin(data1)}, PCA2={bin(data2)}, PCA3={bin(data3)}")
            else:
                card_logger.debug(f"Состояние контроллеров: PCA1={bin(data1)}, PCA2={bin(data2)}")
        except Exception as e:
            logger.error(f"Ошибка при чтении состояния контроллеров: {str(e)}")
            
        if card_present:
            is_empty = False
    except Exception as e:
        logger.error(f"Ошибка в cardreader_find: {str(e)}")


def main():
    global room_controller, door_just_closed, active_key, relay1_controller, relay2_controller, relay3_controller
    
    rfid_handler = None
    card_task = None
    check_pin_task = None
    
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
        check_pin_task.daemon = False  # Изменено с daemon=True на False
        check_pin_task.start()
        logger.info("Задача проверки пинов запущена")
        
        # Проверка состояния картоприемника
        logger.info(f"Запуск задачи проверки картоприемника (интервал: 4 сек)...")
        cardreader_find()
        
        # Инициализация неблокирующего обработчика RFID
        logger.info("Запуск потока чтения RFID...")
        rfid_thread = threading.Thread(target=rfid_thread_function)
        rfid_thread.daemon = True
        rfid_thread.start()
        logger.info("Поток чтения RFID запущен")
        
        # Включаем устройства
        logger.info("Включение устройств по умолчанию...")
        turn_on()
        logger.info("Устройства включены")
        
        logger.info("=== СИСТЕМА ГОТОВА К РАБОТЕ ===")
        
        # Передаем управление в основной цикл FastAPI
        while True:
            time.sleep(1)
            
    except ProgramKilled:
        logger.info("Получен сигнал завершения программы, очистка...")
        
        # Безопасная остановка задач
        if rfid_handler:
            logger.info("Останавливаем RFID обработчик...")
            rfid_handler.stop()
            
        if card_task:
            logger.info("Останавливаем задачу проверки карт...")
            card_task.stop()
            
        if check_pin_task:
            logger.info("Останавливаем задачу проверки пинов...")
            check_pin_task.stop()
            
        logger.info("Задачи остановлены")
        
        # Сброс всех реле при завершении программы
        try:
            logger.info("Сброс всех контроллеров реле перед завершением...")
            
            # Сброс реле
            if relay1_controller:
                relay1_controller.reset_all()
            if relay2_controller:
                relay2_controller.reset_all()
            if hasattr(relay3_controller, 'device_available') and relay3_controller and relay3_controller.device_available:
                relay3_controller.reset_all()
            
            logger.info("Все контроллеры реле сброшены")
        except Exception as e:
            logger.error(f"Ошибка при сбросе реле: {str(e)}")
        
        # Явный выход для остановки всех процессов
        os._exit(0)
            
    except Exception as e:
        logger.error(f"Критическая ошибка в основном цикле: {str(e)}")
        
        # Безопасная остановка задач
        if rfid_handler:
            try:
                logger.info("Останавливаем RFID обработчик...")
                rfid_handler.stop()
            except:
                pass
            
        if card_task:
            try:
                logger.info("Останавливаем задачу проверки карт...")
                card_task.stop()
            except:
                pass
            
        if check_pin_task:
            try:
                logger.info("Останавливаем задачу проверки пинов...")
                check_pin_task.stop()
            except:
                pass
        
        # Попытка сбросить реле при критической ошибке
        try:
            logger.info("Попытка сбросить все реле при критической ошибке...")
            
            # Сброс реле
            if relay1_controller:
                relay1_controller.reset_all()
            if relay2_controller:
                relay2_controller.reset_all()
            if hasattr(relay3_controller, 'device_available') and relay3_controller and relay3_controller.device_available:
                relay3_controller.reset_all()
            
            logger.info("Реле сброшены")
        except Exception as reset_error:
            logger.error(f"Не удалось сбросить реле: {str(reset_error)}")
            
        # Явный выход для остановки всех процессов
        os._exit(1)

# Обработка сигналов завершения для корректного освобождения ресурсов

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


@app.on_event("startup")
async def on_startup():
    print("Starting server...")
    logging.basicConfig()
    print("Server started")

# Запуск основного потока
thread = threading.Thread(target=main)
thread.daemon = False    # Поток будет остановлен, когда завершится основной поток
thread.start()

@app.on_event("shutdown")
async def on_shutdown():
    print("Shutting down server...")
    signal_handler(signal.SIGTERM, None)  # Вызываем обработчик сигнала для корректной остановки
    print("Server shutdown complete")
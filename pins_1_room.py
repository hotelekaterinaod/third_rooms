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
    """
    Получение активных карт с новой логикой отбора:
    
    1. Группируем ключи только по типу (tip: 0-9)
    2. Для каждого типа выбираем ключ с самой свежей датой tekdat
    3. Максимум может быть 10 активных ключей (по одному на каждый тип)
    4. Затем фильтруем по датам активности (dstart <= now <= dend)
    """
    global active_cards, count_keys
    
    try:
        cursor = get_db_connection().cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Получаем все записи ключей для комнаты (без фильтрации по датам)
        sql = """
        SELECT * FROM table_kluch 
        WHERE num = {room_number}
        """.format(room_number=system_config.room_number)
        logger.info("SQL запрос для получения всех ключей: {sql}".format(sql=sql))

        cursor.execute(sql)
        all_keys = cursor.fetchall()
        
        logger.info("Найдено всего записей ключей для комнаты {room_number}: {count}".format(
            room_number=system_config.room_number, count=len(all_keys)))
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
                    logger.debug("Обновлен актуальный ключ для tip {tip}: key_id={key_id}, tekdat={tekdat}".format(
                        tip=tip, key_id=key_id, tekdat=tekdat))
                    
            except Exception as e:
                logger.error("Ошибка при обработке записи ключа: {error}".format(error=str(e)))
                continue
        
        logger.info("Найдено уникальных типов ключей (tip): {count} из возможных 10 (0-9)".format(
            count=len(keys_by_tip)))
        
        # Фильтруем по датам активности только самые свежие ключи для каждого типа
        active_key_list = []
        for tip, key_data in keys_by_tip.items():
            key_row = key_data['key_row']
            
            try:
                # Проверяем даты активности (правильная индексация)
                dstart = key_row[2] if len(key_row) > 2 else None
                dend = key_row[3] if len(key_row) > 3 else None
                
                current_time = datetime.now()
                
                # Обработка dstart
                dstart_datetime = None
                if dstart is not None:
                    if isinstance(dstart, str):
                        try:
                            dstart_datetime = datetime.strptime(dstart, "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            logger.warning("Неверный формат dstart: {dstart}".format(dstart=dstart))
                            dstart_datetime = None
                    elif isinstance(dstart, datetime):
                        dstart_datetime = dstart
                    else:
                        logger.warning("Неизвестный тип dstart: {dtype}, значение: {value}".format(
                            dtype=type(dstart), value=dstart))
                        dstart_datetime = None
                
                # Обработка dend
                dend_datetime = None
                if dend is not None:
                    if isinstance(dend, str):
                        try:
                            dend_datetime = datetime.strptime(dend, "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            logger.warning("Неверный формат dend: {dend}".format(dend=dend))
                            dend_datetime = None
                    elif isinstance(dend, datetime):
                        dend_datetime = dend
                    else:
                        logger.warning("Неизвестный тип dend: {dtype}, значение: {value}".format(
                            dtype=type(dend), value=dend))
                        dend_datetime = None
                
                # Проверяем, что ключ активен в текущее время
                start_valid = dstart_datetime is None or dstart_datetime <= current_time
                end_valid = dend_datetime is None or dend_datetime >= current_time
                
                if start_valid and end_valid:
                    active_key_list.append(key_row)
                    logger.debug("Ключ {key_id} (tip: {tip}) прошел проверку дат активности".format(
                        key_id=key_data['key_id'], tip=key_data['tip']))
                else:
                    logger.debug("Ключ {key_id} (tip: {tip}) не прошел проверку дат: start_valid={start_valid}, end_valid={end_valid}".format(
                        key_id=key_data['key_id'], tip=key_data['tip'], start_valid=start_valid, end_valid=end_valid))
                    
            except Exception as e:
                logger.error("Ошибка при проверке дат активности ключа {key_id}: {error}".format(
                    key_id=key_data.get('key_id', 'неизвестен'), error=str(e)))
                continue
        
        logger.info("Найдено активных ключей после обработки: {count}".format(count=len(active_key_list)))
        
        # Логируем подробную информацию о каждом активном ключе
        if active_key_list:
            logger.info("=== АКТИВНЫЕ КЛЮЧИ С ПОЛНОЙ ИНФОРМАЦИЕЙ ===")
            logger.info("Всего активных типов ключей: {count} из 10 возможных (tip: 0-9)".format(
                count=len(active_key_list)))
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
                    additional_info = ", поля БД: {fields} полей".format(fields=len(key_row)) if len(key_row) > 7 else ""
                    
                    logger.info("Ключ TIP #{tip}: ID={key_id}, TEKDAT={tekdat}, DSTART={dstart}, DEND={dend}, NUM={num}{additional_info}".format(
                        tip=tip, key_id=key_id, tekdat=tekdat, dstart=dstart, dend=dend, num=num, additional_info=additional_info))
                    
                except Exception as e:
                    logger.error("Ошибка при логировании ключа #{index}: {error}".format(index=i+1, error=str(e)))
            logger.info("=== КОНЕЦ СПИСКА АКТИВНЫХ КЛЮЧЕЙ ===")
        else:
            logger.info("Активных ключей не найдено")
        
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
            for num_val, id_val in keys_for_rpi_update:
                sql_update = "UPDATE table_kluch SET rpi = 1 WHERE num = {num} AND id = '{id}'".format(
                    num=num_val,
                    id=str(id_val).strip()
                )
                try:
                    cursor.execute(sql_update)
                except Exception as e:
                    logger.error("Ошибка UPDATE rpi для id {id}: {err}".format(id=id_val, err=str(e)))
            try:
                get_db_connection().commit()
                logger.info("Success update rpi for changed rows")
            except Exception as e:
                logger.error("Commit error after rpi bulk updates: {err}".format(err=str(e)))
        else:
            logger.debug("Нет строк для обновления rpi")

        # Сохраняем количество активных ключей (по типам) для диагностики
        count_keys = len(active_key_list)
        
    except Exception as e:
        logger.error("Ошибка при получении активных карт: {error}".format(error=str(e)))
        
    return active_cards


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
            logger.info("No key {key}".format(key=key_))
    except Exception as e:
        print("Error in rfid {error}".format(error=e))
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

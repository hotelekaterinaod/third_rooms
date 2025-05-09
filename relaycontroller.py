import smbus
import time
import threading
import logging
from config import logger

I2C_LOCK = threading.RLock()

class RelayController:
    def __init__(self, address, bus_num=1, retry_attempts=3, delay=0.1):
        """
        Конструктор инициализирует I2C-шину и адрес устройства.
        """
        self.__address = address
        self.__bus = smbus.SMBus(bus_num)
        self.__state = 0xFF  # Начальное состояние (все биты установлены в 1)
        self.__retry_attempts = retry_attempts
        self.__delay = delay
        
        # Инициализация с повторными попытками
        success = self.__write_with_retry(0x09, self.__state)
        if success:
            logger.info(f"Инициализация контроллера реле по адресу {hex(self.__address)}, начальное состояние: {bin(self.__state)}")
        else:
            logger.error(f"Не удалось инициализировать контроллер реле по адресу {hex(self.__address)}")
    
    def __write_with_retry(self, register, value):
        """
        Запись в регистр с повторными попытками при ошибке
        
        :param register: Адрес регистра
        :param value: Значение для записи
        :return: True при успехе, False при неудаче
        """
        for attempt in range(self.__retry_attempts):
            try:
                with I2C_LOCK:  # Блокировка I2C
                    self.__bus.write_byte_data(self.__address, register, value)
                time.sleep(self.__delay)  # Задержка после операции
                return True
            except Exception as e:
                if attempt < self.__retry_attempts - 1:
                    logger.warning(f"Ошибка при записи в регистр {register} контроллера {hex(self.__address)} (попытка {attempt+1}/{self.__retry_attempts}): {str(e)}")
                    time.sleep(self.__delay * 2)  # Увеличенная задержка при ошибке
                else:
                    logger.error(f"Не удалось записать в регистр {register} контроллера {hex(self.__address)} после {self.__retry_attempts} попыток: {str(e)}")
                    return False
    
    def __read_with_retry(self, register=None):
        """
        Чтение из регистра с повторными попытками при ошибке
        
        :param register: Адрес регистра (если None, чтение текущего состояния)
        :return: Прочитанное значение или None при ошибке
        """
        for attempt in range(self.__retry_attempts):
            try:
                with I2C_LOCK:  # Блокировка I2C
                    if register is None:
                        value = self.__bus.read_byte(self.__address)
                    else:
                        value = self.__bus.read_byte_data(self.__address, register)
                time.sleep(self.__delay)  # Задержка после операции
                return value
            except Exception as e:
                if attempt < self.__retry_attempts - 1:
                    logger.warning(f"Ошибка при чтении из регистра {register} контроллера {hex(self.__address)} (попытка {attempt+1}/{self.__retry_attempts}): {str(e)}")
                    time.sleep(self.__delay * 2)  # Увеличенная задержка при ошибке
                else:
                    logger.error(f"Не удалось прочитать из регистра {register} контроллера {hex(self.__address)} после {self.__retry_attempts} попыток: {str(e)}")
                    return None
    
    def set_state(self, state, delay=0.1):
        """
        Устанавливает полное состояние для всех битов сразу.
        """
        try:
            old_state = self.__state
            self.__state = state
            logger.info(f"Установка состояния для контроллера {hex(self.__address)}: {bin(old_state)} -> {bin(self.__state)}")
            self.__bus.write_byte_data(self.__address, 0x09, self.__state)
            time.sleep(delay)
            return True
        except Exception as e:
            logger.error(f"Ошибка при установке состояния для контроллера {hex(self.__address)}: {str(e)}")
            return False
    
    def set_bit(self, bit, delay=0.1):
        """
        Устанавливает конкретный бит в 1, обновляя состояние.
        """
        try:
            old_state = self.__state
            self.__state |= (1 << bit)  # Устанавливаем бит в 1
            logger.info(f"Установка бита {bit} для контроллера {hex(self.__address)}: {bin(old_state)} -> {bin(self.__state)}")
            self.__bus.write_byte_data(self.__address, 0x09, self.__state)
            time.sleep(delay)
            return True
        except Exception as e:
            logger.error(f"Ошибка при установке бита {bit} для контроллера {hex(self.__address)}: {str(e)}")
            return False
    
    def clear_bit(self, bit, delay=0.1):
        """
        Сбрасывает конкретный бит в 0, обновляя состояние.
        """
        try:
            old_state = self.__state
            self.__state &= ~(1 << bit)  # Сбрасываем бит в 0
            logger.info(f"Сброс бита {bit} для контроллера {hex(self.__address)}: {bin(old_state)} -> {bin(self.__state)}")
            self.__bus.write_byte_data(self.__address, 0x09, self.__state)
            time.sleep(delay)
            return True
        except Exception as e:
            logger.error(f"Ошибка при сбросе бита {bit} для контроллера {hex(self.__address)}: {str(e)}")
            return False
    
    def toggle_bit(self, bit, delay=0.1):
        """
        Переключает бит (вкл/выкл), обновляя состояние.
        """
        try:
            old_state = self.__state
            self.__state ^= (1 << bit)  # Инвертируем бит
            logger.info(f"Переключение бита {bit} для контроллера {hex(self.__address)}: {bin(old_state)} -> {bin(self.__state)}")
            self.__bus.write_byte_data(self.__address, 0x09, self.__state)
            time.sleep(delay)
            return True
        except Exception as e:
            logger.error(f"Ошибка при переключении бита {bit} для контроллера {hex(self.__address)}: {str(e)}")
            return False
    
    def check_bit(self, bit):
        """
        Проверяет состояние конкретного бита (0 или 1).
        """
        return 1 if (self.__state & (1 << bit)) else 0
    
    def get_state(self):
        """
        Возвращает текущее состояние всех битов в виде целого числа.
        """
        return self.__state
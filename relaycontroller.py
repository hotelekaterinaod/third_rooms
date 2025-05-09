import smbus
import time
import logging
from config import logger

class RelayController:
    def __init__(self, address, bus_num=1):
        """
        Конструктор инициализирует I2C-шину и адрес устройства.
        """
        self.__address = address
        self.__bus = smbus.SMBus(bus_num)
        self.__state = 0xFF  # Начальное состояние (все биты установлены в 1, в десятичном формате)
        
        try:
            self.__bus.write_byte_data(self.__address, 0x09, self.__state)
            logger.info(f"Инициализация контроллера реле по адресу {hex(self.__address)}, начальное состояние: {bin(self.__state)}")
        except Exception as e:
            logger.error(f"Ошибка при инициализации контроллера реле {hex(self.__address)}: {str(e)}")
            raise
    
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
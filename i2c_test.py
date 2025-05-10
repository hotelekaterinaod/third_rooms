#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import smbus
import time
import logging

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class RelayControllerTest:
    """
    Тестовая версия класса RelayController для отладки проблем с I2C
    """
    def __init__(self, address):
        self.address = address
        self.bus = smbus.SMBus(1)
        self.state = 0xFF  # Начальное состояние - все биты установлены (реле выключены)
        
        try:
            # Чтение текущего состояния
            self.state = self.bus.read_byte(self.address)
            logger.info(f"Инициализирован контроллер реле по адресу 0x{address:02X}, начальное состояние: {bin(self.state)}")
        except Exception as e:
            logger.error(f"Ошибка при инициализации контроллера по адресу 0x{address:02X}: {str(e)}")
            raise
    
    def set_bit(self, bit):
        """Устанавливает бит (выключает реле)"""
        try:
            old_state = self.state
            self.state |= (1 << bit)
            self.bus.write_byte(self.address, self.state)
            logger.info(f"Установка бита {bit} для контроллера 0x{self.address:02X}: {bin(old_state)} -> {bin(self.state)}")
            return True
        except Exception as e:
            logger.error(f"Ошибка при установке бита {bit} для контроллера 0x{self.address:02X}: {str(e)}")
            return False
    
    def clear_bit(self, bit):
        """Сбрасывает бит (включает реле)"""
        try:
            old_state = self.state
            self.state &= ~(1 << bit)
            self.bus.write_byte(self.address, self.state)
            logger.info(f"Сброс бита {bit} для контроллера 0x{self.address:02X}: {bin(old_state)} -> {bin(self.state)}")
            return True
        except Exception as e:
            logger.error(f"Ошибка при сбросе бита {bit} для контроллера 0x{self.address:02X}: {str(e)}")
            return False
    
    def get_state(self):
        """Возвращает текущее состояние контроллера"""
        try:
            self.state = self.bus.read_byte(self.address)
            return self.state
        except Exception as e:
            logger.error(f"Ошибка при чтении состояния контроллера 0x{self.address:02X}: {str(e)}")
            return None

def scan_i2c_bus():
    """Сканирует шину I2C для поиска подключенных устройств"""
    logger.info("Сканирование шины I2C...")
    bus = smbus.SMBus(1)
    found_devices = []
    
    for address in range(0x03, 0x78):
        try:
            bus.read_byte(address)
            logger.info(f"Найдено устройство I2C по адресу: 0x{address:02X}")
            found_devices.append(address)
        except Exception:
            pass
    
    if not found_devices:
        logger.warning("Устройства I2C не обнаружены")
    else:
        logger.info(f"Всего найдено устройств: {len(found_devices)}")
    
    return found_devices

def test_relay_controller(address):
    """Тестирует контроллер реле по указанному адресу"""
    try:
        controller = RelayControllerTest(address)
        logger.info(f"Тестирование контроллера реле по адресу 0x{address:02X}")
        
        # Тестовое включение/выключение каждого бита
        for bit in range(8):
            # Включаем реле (сбрасываем бит)
            controller.clear_bit(bit)
            time.sleep(0.5)
            
            # Выключаем реле (устанавливаем бит)
            controller.set_bit(bit)
            time.sleep(0.5)
        
        logger.info(f"Тест контроллера 0x{address:02X} завершен успешно")
        return True
    except Exception as e:
        logger.error(f"Тест контроллера 0x{address:02X} завершен с ошибкой: {str(e)}")
        return False

def main():
    """Основная функция"""
    try:
        # Сканирование шины I2C
        devices = scan_i2c_bus()
        
        if not devices:
            logger.error("Тестирование невозможно: устройства I2C не обнаружены")
            return
        
        # Тестирование найденных контроллеров
        for address in devices:
            if address in [0x38, 0x39, 0x3b, 0x3B]:  # Возможные адреса контроллеров
                test_relay_controller(address)
    
    except Exception as e:
        logger.error(f"Критическая ошибка: {str(e)}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Прервано пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {str(e)}")
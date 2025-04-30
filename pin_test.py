#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import RPi.GPIO as GPIO
import time
import sys
import logging
import os

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Проверка запуска с правами root
if os.geteuid() != 0:
    logger.error("Скрипт должен быть запущен с правами root (sudo)")
    sys.exit(1)

# Корректные номера GPIO пинов в режиме BCM
VALID_GPIO_PINS = [
    2, 3, 4,    # GPIO2, GPIO3, GPIO4
    17, 27, 22, # GPIO17, GPIO27, GPIO22
    10, 9, 11,  # GPIO10, GPIO9, GPIO11
    5, 6, 13,   # GPIO5, GPIO6, GPIO13
    19, 26,     # GPIO19, GPIO26
    14, 15, 18, # GPIO14, GPIO15, GPIO18
    23, 24, 25, # GPIO23, GPIO24, GPIO25
    8, 7, 12,   # GPIO8, GPIO7, GPIO12
    16, 20, 21  # GPIO16, GPIO20, GPIO21
]

class PinControllerTest:
    """
    Тестовая версия класса PinController для отладки проблем с GPIO
    """
    def __init__(self, pin, callback=None, react_on=GPIO.BOTH, up_down=GPIO.PUD_UP, bouncetime=300, before_callback=None):
        self.pin = pin
        self.callback = callback
        self.react_on = react_on
        self.up_down = up_down
        self.bouncetime = bouncetime
        self.before_callback = before_callback
        self.state = None
        self.event_added = False
        
        logger.info(f"Инициализация пина GPIO{pin}")
        logger.info(f"Параметры: react_on={react_on}, up_down={up_down}, bouncetime={bouncetime}")
        
        try:
            # Настройка GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            
            # Настройка пина как вход
            GPIO.setup(self.pin, GPIO.IN, pull_up_down=self.up_down)
            logger.info(f"Пин GPIO{pin} успешно настроен как INPUT")
            
            # Чтение начального состояния
            self.state = GPIO.input(self.pin)
            logger.info(f"Начальное состояние пина GPIO{pin}: {self.state}")
            
            # Добавление обработчика событий, если указан callback
            if self.callback:
                success = self._add_event_detection()
                if success:
                    self.event_added = True
        
        except Exception as e:
            logger.error(f"Ошибка при инициализации пина GPIO{pin}: {str(e)}")
            raise
    
    def _add_event_detection(self):
        """
        Добавляет обработчик событий для пина
        Возвращает True в случае успеха, False в случае ошибки
        """
        try:
            # Попытка удалить существующие обработчики (если есть)
            try:
                GPIO.remove_event_detect(self.pin)
                logger.info(f"Удален существующий обработчик для пина GPIO{self.pin}")
            except:
                pass
            
            # Попробуем более простой подход: без обертывания колбэка
            try:
                if self.before_callback:
                    # С предварительным колбэком
                    def combined_callback(channel):
                        self.before_callback(self)
                        self.callback(self)
                    
                    GPIO.add_event_detect(self.pin, self.react_on, callback=combined_callback, bouncetime=self.bouncetime)
                else:
                    # Только основной колбэк
                    GPIO.add_event_detect(self.pin, self.react_on, callback=lambda channel: self.callback(self), 
                                         bouncetime=self.bouncetime)
                
                logger.info(f"Обработчик событий для пина GPIO{self.pin} добавлен успешно")
                return True
            except Exception as e:
                logger.error(f"Ошибка при добавлении обработчика событий для пина GPIO{self.pin}: {str(e)}")
                
                # Пробуем альтернативный метод (без колбэка, с wait_for_edge в отдельном потоке)
                logger.info(f"Попытка использовать альтернативный метод обнаружения событий для пина GPIO{self.pin}")
                return False
        
        except Exception as e:
            logger.error(f"Ошибка при настройке обработчика событий для пина GPIO{self.pin}: {str(e)}")
            return False
    
    def check_pin(self):
        """
        Проверяет текущее состояние пина
        """
        try:
            old_state = self.state
            self.state = GPIO.input(self.pin)
            
            if old_state != self.state:
                logger.info(f"Изменено состояние пина GPIO{self.pin}: {old_state} -> {self.state}")
            
            return self.state
        except Exception as e:
            logger.error(f"Ошибка при проверке состояния пина GPIO{self.pin}: {str(e)}")
            return None

def dummy_callback(self):
    """Заглушка для колбэка"""
    logger.info(f"Вызван колбэк для пина GPIO{self.pin}")

def test_pin_basic(pin_number):
    """Базовое тестирование пина (без обработчиков событий)"""
    try:
        # Проверка валидности GPIO пина
        if pin_number not in VALID_GPIO_PINS:
            logger.error(f"GPIO{pin_number} не является допустимым GPIO пином в режиме BCM")
            return False
            
        # Настраиваем пин как вход
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(pin_number, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        
        # Читаем состояние пина
        state = GPIO.input(pin_number)
        logger.info(f"Пин GPIO{pin_number} настроен как INPUT, состояние: {state}")
        
        # Пробуем добавить и удалить обработчик событий
        try:
            GPIO.add_event_detect(pin_number, GPIO.FALLING, bouncetime=300)
            logger.info(f"Обработчик событий для пина GPIO{pin_number} добавлен успешно")
            GPIO.remove_event_detect(pin_number)
            logger.info(f"Обработчик событий для пина GPIO{pin_number} удален успешно")
            return True
        except Exception as e:
            logger.error(f"Ошибка при добавлении обработчика события для пина GPIO{pin_number}: {str(e)}")
            return False
            
    except Exception as e:
        logger.error(f"Ошибка при базовом тестировании пина GPIO{pin_number}: {str(e)}")
        return False

def test_pin_advanced(pin_number):
    """Тестирует пин с использованием PinControllerTest"""
    try:
        # Проверка валидности GPIO пина
        if pin_number not in VALID_GPIO_PINS:
            logger.error(f"GPIO{pin_number} не является допустимым GPIO пином в режиме BCM")
            return False
            
        pin_controller = PinControllerTest(
            pin=pin_number,
            callback=dummy_callback,
            react_on=GPIO.FALLING,
            up_down=GPIO.PUD_UP,
            bouncetime=300
        )
        
        logger.info(f"PinControllerTest для пина GPIO{pin_number} успешно создан")
        
        # Проверяем состояние пина
        state = pin_controller.check_pin()
        logger.info(f"Текущее состояние пина GPIO{pin_number}: {state}")
        
        # Проверяем, был ли добавлен обработчик событий
        if pin_controller.event_added:
            logger.info(f"Обработчик событий для пина GPIO{pin_number} успешно добавлен")
        else:
            logger.warning(f"Не удалось добавить обработчик событий для пина GPIO{pin_number}")
        
        return True
    
    except Exception as e:
        logger.error(f"Тест пина GPIO{pin_number} завершен с ошибкой: {str(e)}")
        return False

def main():
    """Основная функция"""
    try:
        # Очистка перед началом тестов
        GPIO.cleanup()
    except:
        pass
    
    if len(sys.argv) > 1:
        try:
            pin_to_test = int(sys.argv[1])
            logger.info(f"Тестирование пина GPIO{pin_to_test}")
            
            logger.info(f"\n=== Базовое тестирование пина GPIO{pin_to_test} ===")
            basic_test_result = test_pin_basic(pin_to_test)
            
            logger.info(f"\n=== Расширенное тестирование пина GPIO{pin_to_test} ===")
            advanced_test_result = test_pin_advanced(pin_to_test)
            
            if basic_test_result and advanced_test_result:
                logger.info(f"Пин GPIO{pin_to_test} успешно прошел все тесты")
            else:
                logger.warning(f"Пин GPIO{pin_to_test} прошел не все тесты")
        except ValueError:
            logger.error(f"{sys.argv[1]} не является числом")
    else:
        # Тестируем корректные GPIO пины в режиме BCM
        # Выберем несколько пинов для теста
        test_pins = [17, 27, 22, 10, 9, 11]
        logger.info(f"Тестирование {len(test_pins)} пинов")
        
        basic_success = 0
        advanced_success = 0
        failed_pins = []
        
        for pin in test_pins:
            logger.info(f"\n=== Базовое тестирование пина GPIO{pin} ===")
            basic_result = test_pin_basic(pin)
            if basic_result:
                basic_success += 1
                
            logger.info(f"\n=== Расширенное тестирование пина GPIO{pin} ===")
            advanced_result = test_pin_advanced(pin)
            if advanced_result:
                advanced_success += 1
                
            if not (basic_result and advanced_result):
                failed_pins.append(pin)
        
        logger.info("\n=== Результаты тестирования ===")
        logger.info(f"Базовое тестирование: успешно {basic_success} из {len(test_pins)}")
        logger.info(f"Расширенное тестирование: успешно {advanced_success} из {len(test_pins)}")
        
        if failed_pins:
            logger.info(f"Проблемные пины: {failed_pins}")
        else:
            logger.info("Все пины работают нормально")

def test_wait_for_edge():
    """Тестирует метод wait_for_edge вместо add_event_detect"""
    pin = 17  # Используем GPIO17 для теста
    
    logger.info(f"\n=== Тестирование wait_for_edge для пина GPIO{pin} ===")
    
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        
        logger.info(f"Пин GPIO{pin} настроен как INPUT, состояние: {GPIO.input(pin)}")
        logger.info(f"Ожидание события на пине GPIO{pin} в течение 5 секунд...")
        
        # Ждем событие не более 5 секунд
        event_detected = GPIO.wait_for_edge(pin, GPIO.FALLING, timeout=5000)
        
        if event_detected is None:
            logger.info(f"Событие на пине GPIO{pin} не обнаружено в течение таймаута")
        else:
            logger.info(f"Событие на пине GPIO{pin} обнаружено!")
            
        return True
    except Exception as e:
        logger.error(f"Ошибка при тестировании wait_for_edge для пина GPIO{pin}: {str(e)}")
        return False
    finally:
        GPIO.cleanup(pin)

if __name__ == "__main__":
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "--wait-test":
            test_wait_for_edge()
        else:
            main()
    except KeyboardInterrupt:
        logger.info("Прервано пользователем")
        GPIO.cleanup()
    except Exception as e:
        logger.error(f"Критическая ошибка: {str(e)}")
        GPIO.cleanup()
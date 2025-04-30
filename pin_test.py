#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import RPi.GPIO as GPIO
import time
import sys
import logging

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Правильные номера GPIO пинов в режиме BCM
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
                self._add_event_detection()
        
        except Exception as e:
            logger.error(f"Ошибка при инициализации пина GPIO{pin}: {str(e)}")
            raise
    
    def _add_event_detection(self):
        """
        Добавляет обработчик событий для пина
        """
        try:
            # Попытка удалить существующие обработчики (если есть)
            try:
                GPIO.remove_event_detect(self.pin)
                logger.info(f"Удален существующий обработчик для пина GPIO{self.pin}")
            except:
                pass
            
            # Добавление нового обработчика
            if self.before_callback:
                # С предварительным колбэком
                def combined_callback(channel):
                    self.before_callback(self)
                    self.callback(self)
                
                GPIO.add_event_detect(self.pin, self.react_on, callback=combined_callback, bouncetime=self.bouncetime)
            else:
                # Только основной колбэк
                def wrapped_callback(channel):
                    self.callback(self)
                
                GPIO.add_event_detect(self.pin, self.react_on, callback=wrapped_callback, bouncetime=self.bouncetime)
            
            logger.info(f"Обработчик событий для пина GPIO{self.pin} добавлен успешно")
            return True
        
        except Exception as e:
            logger.error(f"Ошибка при добавлении обработчика событий для пина GPIO{self.pin}: {str(e)}")
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

def test_pin(pin_number):
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
        
        logger.info(f"Тест пина GPIO{pin_number} завершен успешно")
        return True
    
    except Exception as e:
        logger.error(f"Тест пина GPIO{pin_number} завершен с ошибкой: {str(e)}")
        return False

def main():
    """Основная функция"""
    GPIO.cleanup()  # Очистка перед началом тестов
    
    if len(sys.argv) > 1:
        try:
            pin_to_test = int(sys.argv[1])
            logger.info(f"Тестирование пина GPIO{pin_to_test}")
            test_pin(pin_to_test)
        except ValueError:
            logger.error(f"{sys.argv[1]} не является числом")
    else:
        # Тестируем корректные GPIO пины в режиме BCM
        # Выберем несколько пинов для теста
        test_pins = [17, 27, 22, 10, 9, 11, 5, 6, 13, 19, 26]
        logger.info(f"Тестирование {len(test_pins)} пинов")
        
        success_count = 0
        failed_pins = []
        
        for pin in test_pins:
            logger.info(f"\n=== Тестирование пина GPIO{pin} ===")
            if test_pin(pin):
                success_count += 1
            else:
                failed_pins.append(pin)
        
        logger.info("\n=== Результаты тестирования ===")
        logger.info(f"Успешно протестировано: {success_count} из {len(test_pins)}")
        if failed_pins:
            logger.info(f"Проблемные пины: {failed_pins}")
        else:
            logger.info("Все пины работают нормально")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Прервано пользователем")
        GPIO.cleanup()
    except Exception as e:
        logger.error(f"Критическая ошибка: {str(e)}")
        GPIO.cleanup()
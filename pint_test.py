#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import time
import sys
import logging
from gpiozero import Button
from signal import pause

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Правильные номера GPIO пинов
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

class GPIOZeroPinTest:
    """
    Класс для тестирования пинов с использованием библиотеки gpiozero
    """
    def __init__(self, pin, pull_up=True, bounce_time=0.3):
        self.pin_number = pin
        self.pull_up = pull_up
        self.bounce_time = bounce_time
        self.button = None
        
        logger.info(f"Инициализация пина GPIO{pin}")
        logger.info(f"Параметры: pull_up={pull_up}, bounce_time={bounce_time}")
        
        try:
            # Инициализация кнопки (датчика ввода)
            self.button = Button(
                pin=pin, 
                pull_up=pull_up, 
                bounce_time=bounce_time
            )
            
            logger.info(f"Пин GPIO{pin} успешно настроен как INPUT")
            logger.info(f"Начальное состояние пина GPIO{pin}: {not self.button.is_pressed}")
            
            # Добавление обработчиков событий
            self.button.when_pressed = self._on_pressed
            self.button.when_released = self._on_released
            
            logger.info(f"Обработчики событий для пина GPIO{pin} добавлены успешно")
            
        except Exception as e:
            logger.error(f"Ошибка при инициализации пина GPIO{pin}: {str(e)}")
            raise
    
    def _on_pressed(self):
        """Обработчик события нажатия (низкий уровень сигнала)"""
        logger.info(f"Сработало событие PRESSED для пина GPIO{self.pin_number}")
    
    def _on_released(self):
        """Обработчик события отпускания (высокий уровень сигнала)"""
        logger.info(f"Сработало событие RELEASED для пина GPIO{self.pin_number}")
    
    def check_pin(self):
        """Проверяет текущее состояние пина"""
        try:
            state = not self.button.is_pressed  # В pull_up режиме логика инвертирована
            logger.info(f"Текущее состояние пина GPIO{self.pin_number}: {state}")
            return state
        except Exception as e:
            logger.error(f"Ошибка при проверке состояния пина GPIO{self.pin_number}: {str(e)}")
            return None
    
    def cleanup(self):
        """Освобождает ресурсы"""
        try:
            if self.button:
                self.button.close()
                logger.info(f"Ресурсы для пина GPIO{self.pin_number} освобождены")
        except Exception as e:
            logger.error(f"Ошибка при освобождении ресурсов пина GPIO{self.pin_number}: {str(e)}")

def test_pin(pin_number):
    """Тестирует пин с использованием GPIOZeroPinTest"""
    pin_controller = None
    try:
        # Проверка валидности GPIO пина
        if pin_number not in VALID_GPIO_PINS:
            logger.error(f"GPIO{pin_number} не является допустимым GPIO пином")
            return False
            
        pin_controller = GPIOZeroPinTest(
            pin=pin_number,
            pull_up=True,
            bounce_time=0.3
        )
        
        logger.info(f"GPIOZeroPinTest для пина GPIO{pin_number} успешно создан")
        
        # Проверяем состояние пина
        state = pin_controller.check_pin()
        
        # Даем немного времени для возможного срабатывания событий
        time.sleep(0.5)
        
        logger.info(f"Тест пина GPIO{pin_number} завершен успешно")
        return True
    
    except Exception as e:
        logger.error(f"Тест пина GPIO{pin_number} завершен с ошибкой: {str(e)}")
        return False
    
    finally:
        # Освобождаем ресурсы
        if pin_controller:
            pin_controller.cleanup()

def main():
    """Основная функция"""
    if len(sys.argv) > 1:
        try:
            pin_to_test = int(sys.argv[1])
            logger.info(f"Тестирование пина GPIO{pin_to_test}")
            test_pin(pin_to_test)
        except ValueError:
            logger.error(f"{sys.argv[1]} не является числом")
    else:
        # Тестируем несколько пинов
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
    except Exception as e:
        logger.error(f"Критическая ошибка: {str(e)}")
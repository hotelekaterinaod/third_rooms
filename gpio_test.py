#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import RPi.GPIO as GPIO
import time
import sys

"""
Тестовый скрипт для проверки работы GPIO пинов на Raspberry Pi
"""

# Список пинов для тестирования
PINS_TO_TEST = [1, 7, 8, 10, 12, 13, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27]

def setup_gpio():
    """Настройка GPIO"""
    print("Настройка GPIO...")
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    print("GPIO настроен в режиме BCM")

def test_pin_read(pin):
    """Проверка чтения состояния пина"""
    try:
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        state = GPIO.input(pin)
        print(f"Пин {pin} настроен как INPUT, состояние: {state}")
        return True
    except Exception as e:
        print(f"Ошибка при настройке пина {pin} как INPUT: {str(e)}")
        return False

def test_pin_edge_detection(pin):
    """Проверка добавления обработчика событий для пина"""
    try:
        def callback(channel):
            print(f"Событие на пине {channel}")
        
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.add_event_detect(pin, GPIO.FALLING, callback=callback, bouncetime=300)
        print(f"Пин {pin}: обработчик события успешно добавлен (ожидание события FALLING)")
        return True
    except Exception as e:
        print(f"Ошибка при добавлении обработчика события для пина {pin}: {str(e)}")
        return False

def test_specific_pin(pin_number):
    """Проверка конкретного пина"""
    print(f"\n=== Тестирование пина {pin_number} ===")
    read_ok = test_pin_read(pin_number)
    if read_ok:
        edge_ok = test_pin_edge_detection(pin_number)
        return edge_ok
    return False

def test_all_pins():
    """Проверка всех пинов из списка"""
    print("\n=== Начало тестирования всех пинов ===")
    success_count = 0
    failed_pins = []
    
    for pin in PINS_TO_TEST:
        if test_specific_pin(pin):
            success_count += 1
        else:
            failed_pins.append(pin)
    
    print("\n=== Результаты тестирования ===")
    print(f"Успешно протестировано: {success_count} из {len(PINS_TO_TEST)}")
    if failed_pins:
        print(f"Проблемные пины: {failed_pins}")
    else:
        print("Все пины работают нормально")

def main():
    """Основная функция"""
    setup_gpio()
    
    if len(sys.argv) > 1:
        try:
            pin_to_test = int(sys.argv[1])
            test_specific_pin(pin_to_test)
        except ValueError:
            print(f"Ошибка: {sys.argv[1]} не является числом")
    else:
        test_all_pins()
    
    print("\nТестирование завершено. Очистка GPIO...")
    GPIO.cleanup()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nПрервано пользователем")
        GPIO.cleanup()
    except Exception as e:
        print(f"\nКритическая ошибка: {str(e)}")
        GPIO.cleanup()
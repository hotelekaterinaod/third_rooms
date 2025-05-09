import time
import RPi.GPIO as GPIO

def test_gpio_directly():
    print("Testing GPIO directly with RPi.GPIO")
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(17, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    time.sleep(1)
    value = GPIO.input(17)
    print(f"GPIO 17 value: {value}")
    GPIO.cleanup()

try:
    test_gpio_directly()
    print("Direct GPIO test successful")
except Exception as e:
    print(f"Direct GPIO test failed: {e}")

# Try a second approach
try:
    print("\nTesting with a different GPIO pin")
    GPIO.setmode(GPIO.BCM)
    # Try a different pin
    GPIO.setup(5, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    time.sleep(1)
    value = GPIO.input(5)
    print(f"GPIO 5 value: {value}")
    GPIO.cleanup()
except Exception as e:
    print(f"Alternative pin test failed: {e}")


from gpiozero import Button
from gpiozero.pins.rpigpio import RPiGPIOFactory
import time

# Создание фабрики пинов для RPi.GPIO
pin_factory = RPiGPIOFactory()

try:
    # Использование кнопки без edge_detection
    button = Button(17, pull_up=True, pin_factory=pin_factory)
    
    # Отключение прерываний edge detection
    # Вместо автоматических событий будем использовать опрос
    button.when_pressed = None
    button.when_released = None
    
    print(f"Кнопка настроена. Текущее значение: {button.value}")
    
    # Опрос вместо edge detection
    for i in range(10):
        print(f"Значение пина: {button.value}")
        time.sleep(0.5)
    
except Exception as e:
    print(f"Ошибка: {e}")
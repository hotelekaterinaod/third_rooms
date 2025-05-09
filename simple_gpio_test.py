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
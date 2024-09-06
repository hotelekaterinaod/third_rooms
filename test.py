import RPi.GPIO as GPIO

GPIO.setmode(GPIO.BOARD)

pins_to_test = [7, 11, 13, 15]  # Замените на нужные вам пины

for pin in pins_to_test:
    try:
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
        GPIO.add_event_detect(pin, GPIO.RISING)
        print(f"Pin {pin} is available for event detection")
    except RuntimeError as e:
        print(f"Pin {pin} is not available: {e}")

GPIO.cleanup()
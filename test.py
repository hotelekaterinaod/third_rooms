import pigpio

pi = pigpio.pi()

pins_to_test = [4, 17, 27, 22]  # Замена номеров GPIO на ваши

for pin in pins_to_test:
    try:
        pi.set_mode(pin, pigpio.INPUT)
        pi.set_pull_up_down(pin, pigpio.PUD_DOWN)
        pi.callback(pin, pigpio.RISING_EDGE, lambda x, y, z: print(f"Pin {pin} triggered"))
        print(f"Pin {pin} is set up for edge detection")
    except Exception as e:
        print(f"Pin {pin} setup failed: {e}")

pi.stop()
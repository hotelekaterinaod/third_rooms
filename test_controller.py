import pigpio
import time
from config import logger


class PinController:
    pin = None
    state = 0

    def __init__(self, pi, pin, callback, up_down=pigpio.PUD_UP, react_on=pigpio.EITHER_EDGE, before_callback=None,
                 bouncetime=100):
        logger.info("Pin controller for {} pin has been initiated".format(pin))
        self.pi = pi  # Экземпляр pigpio.pi()
        self.pin = self.validate_pin(pin)
        self.callback = callback
        self.before_callback = before_callback
        self.bouncetime = bouncetime * 1000  # В микросекундах для pigpio

        assert up_down in (pigpio.PUD_UP, pigpio.PUD_DOWN), \
            "This is weird! Pull-up-down parameter can be either UP or DOWN. {} given".format(up_down)

        self.pi.set_mode(self.pin, pigpio.INPUT)
        self.pi.set_pull_up_down(self.pin, up_down)

        # Добавление обработки события через pigpio.callback
        self.pi.callback(self.pin, react_on, self.gpio_wrapper)

    def validate_pin(self, pin):
        if not pin:
            raise Exception("Pin number expected.")
        if not isinstance(pin, (str, int)):
            raise Exception("Integer expected")
        if isinstance(pin, str) and not pin.isdigit():
            raise Exception("Integer expected")
        pin = int(pin)
        if pin < 0 or 27 < pin:
            raise Exception("BCM mode provides numbers [0; 27]. {} given.".format(pin))
        return pin

    def callback(self, gpio, level, tick):
        pass

    def before_callback(self, gpio, level, tick):
        pass

    def check_pin(self):
        self.handler("Check for {pin} pin".format(pin=self.pin))
        logger.info("Check for {pin} pin".format(pin=self.pin))

    def handler(self, message):
        time.sleep(0.01)
        self.state = self.pi.read(self.pin)
        self.before_callback(self.pin, self.state, None)
        if not self.state:
            time.sleep(0.01)
            self.state = self.pi.read(self.pin)
            if not self.state:
                self.callback(self.pin, self.state, None)

    def gpio_wrapper(self, pin, level, tick):
        if pin != 22:
            logger.info("Callback handler for pin {pin}".format(pin=pin))
        self.handler("Callback handler for pin {pin}".format(pin=pin))


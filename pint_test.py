from gpiozero import Button
from gpiozero.pins.rpigpio import RPiGPIOFactory

# Force using RPi.GPIO instead of lgpio
pin_factory = RPiGPIOFactory()

# Then initialize your buttons with this factory
button = Button(17, pull_up=True, bounce_time=0.3, pin_factory=pin_factory)
import smbus
from config import logger


class RelayController:

    __address = None
    __bus = None
    __state = 0xff

    def __init__(self, address):
        self.__address = address
        self.__bus = smbus.SMBus(1)
        self.__bus.write_byte_data(self.__address, 0x09, self.__state)

    def clear_bit(self, bit):
        self.__state &= ~(1 << bit)
        self.__bus.write_byte_data(self.__address, 0x09, self.__state)

    def set_bit(self, bit):
        logger.info(f"Before for {self.__address} - state  {self.__state}")
        self.__state |= 1 << bit
        logger.info(f"Set after state    {self.__state}")
        self.__bus.write_byte_data(self.__address, 0x09, self.__state)

    def toggle_bit(self, bit):
        self.__state ^= 1 << bit
        self.__bus.write_byte_data(self.__address, 0x09, self.__state)

    def check_bit(self, bit):
        return (self.__state >> bit) & 1

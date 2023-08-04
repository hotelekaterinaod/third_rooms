import smbus


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
        print(f"Set {self.__address} -  {self.__state}")
        self.__state |= 1 << bit
        print(f"Set 2 {self.__state}")
        self.__bus.write_byte_data(self.__address, 0x09, self.__state)

    def toggle_bit(self, bit):
        self.__state ^= 1 << bit
        self.__bus.write_byte_data(self.__address, 0x09, self.__state)

    def check_bit(self, bit):
        return (self.__state >> bit) & 1

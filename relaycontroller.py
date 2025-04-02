import smbus
import time

class RelayController:
    def __init__(self, address, bus_num=1):
        """
        Конструктор инициализирует I2C-шину и адрес устройства.
        """
        self.__address = address
        self.__bus = smbus.SMBus(bus_num)
        self.__state = '11111111'  # Начальное состояние (все биты установлены в 1)
        self.__bus.write_byte_data(self.__address, 0x09, int(self.__state, 2))
        print(f"Инициализация контроллера реле по адресу {hex(self.__address)}, начальное состояние: {bin(int(self.__state, 2))}")

    def set_state(self, state, delay=0.2):
        """
        Устанавливает полное состояние для всех битов сразу.
        """
        self.__state = f'{state:08b}'  # Преобразуем в двоичное строковое представление
        print(f"Установка состояния {bin(int(self.__state, 2))} для контроллера {hex(self.__address)}")
        self.__bus.write_byte_data(self.__address, 0x09, int(self.__state, 2))
        time.sleep(delay)

    def set_bit(self, bit, delay=0.2):
        """
        Устанавливает конкретный бит в 1, обновляя состояние.
        """
        old_state = self.__state
        state_list = list(self.__state)
        state_list[7 - bit] = '1'
        self.__state = ''.join(state_list)
        print(f"Установка бита {bit} для контроллера {hex(self.__address)}: {old_state} -> {self.__state}")
        self.__bus.write_byte_data(self.__address, 0x09, int(self.__state, 2))
        time.sleep(delay)

    def clear_bit(self, bit, delay=0.2):
        """
        Сбрасывает конкретный бит в 0, обновляя состояние.
        """
        old_state = self.__state
        state_list = list(self.__state)
        state_list[7 - bit] = '0'  # Меняем бит на 0
        self.__state = ''.join(state_list)
        print(f"Сброс бита {bit} для контроллера {hex(self.__address)}: {old_state} -> {self.__state}")
        self.__bus.write_byte_data(self.__address, 0x09, int(self.__state, 2))
        time.sleep(delay)

    def toggle_bit(self, bit, delay=0.2):
        """
        Переключает бит (вкл/выкл), обновляя состояние.
        """
        old_state = self.__state
        state_list = list(self.__state)
        state_list[7 - bit] = '0' if state_list[7 - bit] == '1' else '1' # Инвертируем бит
        self.__state = ''.join(state_list)
        print(f"Переключение бита {bit} для контроллера {hex(self.__address)}: {old_state} -> {self.__state}")
        self.__bus.write_byte_data(self.__address, 0x09, int(self.__state, 2))
        time.sleep(delay)

    def check_bit(self, bit):
        """
        Проверяет состояние конкретного бита (0 или 1).
        """
        bit_state = self.__state[7 - bit]
        return bit_state

    def get_state(self):
        """
        Возвращает текущее состояние всех битов в виде целого числа.

        """
        return int(self.__state, 2)  # Преобразуем строку в число

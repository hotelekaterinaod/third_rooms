import time
from relaycontroller import RelayController

def test_relay_bit_operations():
    # Создаем контроллер реле по адресу 0x38 и 0x39
    relay1_controller = RelayController(0x38)
    relay2_controller = RelayController(0x39)

    # Последовательное включение и выключение битов на реле 1
    print("Testing relay 1:")
    for bit in range(8):
        relay1_controller.clear_bit(bit)  # Выключаем бит
        print(f"Relay 1 cleared bit {bit}, current state: {bin(relay1_controller.get_state())}")
        time.sleep(10)

    for bit in range(8):
        relay1_controller.set_bit(bit)  # Включаем бит
        print(f"Relay 1 set bit {bit}, current state: {bin(relay1_controller.get_state())}")
        time.sleep(10)

    # Последовательное включение и выключение битов на реле 2
    print("Testing relay 2:")
    for bit in range(8):
        relay2_controller.clear_bit(bit)  # Выключаем бит
        print(f"Relay 2 cleared bit {bit}, current state: {bin(relay2_controller.get_state())}")
        time.sleep(10)

    for bit in range(8):
        relay2_controller.set_bit(bit)  # Включаем бит
        print(f"Relay 2 set bit {bit}, current state: {bin(relay2_controller.get_state())}")
        time.sleep(10)

if __name__ == "__main__":
    # Запускаем тестовую программу для реле
    test_relay_bit_operations()
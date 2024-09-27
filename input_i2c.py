import time
from relaycontroller import RelayController

def main():
    # Создаем контроллеры для двух реле
    relay1_controller = RelayController(0x38)
    relay2_controller = RelayController(0x39)

    while True:
        try:
            # Выбор реле
            relay_choice = input("Выберите реле (1 или 2): ")
            if relay_choice not in ['1', '2']:
                print("Неверный выбор. Пожалуйста, введите 1 или 2.")
                continue

            # Выбор бита
            bit_choice = input("Введите бит (от 0 до 7): ")
            if not bit_choice.isdigit() or not (0 <= int(bit_choice) <= 7):
                print("Неверный бит. Введите число от 0 до 7.")
                continue
            bit_choice = int(bit_choice)

            # Выбор действия
            action_choice = input("Введите действие (1 - set, 0 - clear): ")
            if action_choice not in ['0', '1']:
                print("Неверное действие. Введите 0 для очистки или 1 для установки.")
                continue
            action_choice = int(action_choice)

            # Выбор контроллера реле
            if relay_choice == '1':
                relay_controller = relay1_controller
            else:
                relay_controller = relay2_controller

            # Выполнение действия
            if action_choice == 1:
                relay_controller.set_bit(bit_choice)
                print(f"Реле {relay_choice}, бит {bit_choice} установлен. Текущее состояние: {bin(relay_controller.get_state())}")
            else:
                relay_controller.clear_bit(bit_choice)
                print(f"Реле {relay_choice}, бит {bit_choice} очищен. Текущее состояние: {bin(relay_controller.get_state())}")

            time.sleep(2)  # Небольшая задержка перед следующим вводом

        except KeyboardInterrupt:
            print("\nВыход из программы...")
            break
        except Exception as e:
            print(f"Произошла ошибка: {e}")

if __name__ == "__main__":
    main()

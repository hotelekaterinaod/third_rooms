import lgpio
import time
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_gpio_pin(pin):
    try:
        # Инициализация lgpio
        h = lgpio.gpiochip_open(0)
        logger.info(f"=== Тестирование пина GPIO{pin} ===")
        
        # Настройка пина как вход с подтяжкой
        lgpio.gpio_claim_input(h, pin, lgpio.SET_PULL_UP)
        logger.info(f"Пин GPIO{pin} настроен как вход с подтяжкой")
        
        # Чтение значения пина
        value = lgpio.gpio_read(h, pin)
        logger.info(f"Значение пина GPIO{pin}: {value}")
        
        # Настройка функции обратного вызова для пина
        def callback(chip, gpio, level, timestamp):
            logger.info(f"Изменение на пине GPIO{pin}: {level}")
        
        # Регистрация функции обратного вызова для обоих фронтов (rising и falling)
        cb_id = lgpio.gpio_set_alert_func(h, pin, callback)
        logger.info(f"Функция обратного вызова установлена для пина GPIO{pin}")
        
        # Подождать 2 секунды для возможных изменений
        logger.info(f"Ожидание 2 секунды для тестирования пина GPIO{pin}...")
        time.sleep(2)
        
        # Отменить функцию обратного вызова
        lgpio.gpio_set_alert_func(h, pin, None)
        
        # Освободить пин
        lgpio.gpio_free(h, pin)
        logger.info(f"Тест пина GPIO{pin} успешно завершен")
        
        # Закрыть чип
        lgpio.gpiochip_close(h)
        return True
    except Exception as e:
        logger.error(f"Ошибка при тестировании пина GPIO{pin}: {str(e)}")
        try:
            lgpio.gpiochip_close(h)
        except:
            pass
        return False

if __name__ == "__main__":
    # Список пинов для тестирования
    pins = [17, 27, 22, 10, 9, 11, 5, 6, 13, 19, 26]
    
    logger.info(f"Тестирование {len(pins)} пинов")
    
    success_count = 0
    failed_pins = []
    
    for pin in pins:
        if test_gpio_pin(pin):
            success_count += 1
        else:
            failed_pins.append(pin)
    
    logger.info("\n=== Результаты тестирования ===")
    logger.info(f"Успешно протестировано: {success_count} из {len(pins)}")
    
    if failed_pins:
        logger.info(f"Проблемные пины: {failed_pins}")
    else:
        logger.info("Все пины работают корректно!")
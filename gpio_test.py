import os
import subprocess
import platform
import sys
import logging
import time

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def run_command(command):
    """Выполняет команду и возвращает результат"""
    try:
        process = subprocess.Popen(
            command, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            shell=True,
            universal_newlines=True
        )
        stdout, stderr = process.communicate()
        return {
            'stdout': stdout,
            'stderr': stderr,
            'returncode': process.returncode
        }
    except Exception as e:
        return {
            'stdout': '',
            'stderr': str(e),
            'returncode': -1
        }

def check_raspi_config():
    """Проверяет настройки GPIO в raspi-config"""
    logger.info("=== Проверка настроек GPIO в raspi-config ===")
    
    # Проверка, включен ли SPI интерфейс
    spi_result = run_command("raspi-config nonint get_spi")
    if spi_result['returncode'] == 0 and spi_result['stdout'].strip() == '0':
        logger.info("SPI интерфейс: ВКЛЮЧЕН")
    else:
        logger.warning("SPI интерфейс: ОТКЛЮЧЕН или ошибка проверки")
    
    # Проверка, включен ли I2C интерфейс
    i2c_result = run_command("raspi-config nonint get_i2c")
    if i2c_result['returncode'] == 0 and i2c_result['stdout'].strip() == '0':
        logger.info("I2C интерфейс: ВКЛЮЧЕН")
    else:
        logger.warning("I2C интерфейс: ОТКЛЮЧЕН или ошибка проверки")
    
    # Проверка, включен ли 1-Wire интерфейс
    onewire_result = run_command("raspi-config nonint get_w1")
    if onewire_result['returncode'] == 0 and onewire_result['stdout'].strip() == '0':
        logger.info("1-Wire интерфейс: ВКЛЮЧЕН")
    else:
        logger.warning("1-Wire интерфейс: ОТКЛЮЧЕН или ошибка проверки")

def check_gpio_group():
    """Проверяет, находится ли текущий пользователь в группе gpio"""
    logger.info("=== Проверка групп пользователя ===")
    
    # Получение текущего пользователя
    username = os.getenv('USER') or os.getenv('LOGNAME') or run_command("whoami")['stdout'].strip()
    logger.info(f"Текущий пользователь: {username}")
    
    # Проверка групп пользователя
    groups_result = run_command(f"groups {username}")
    if groups_result['returncode'] == 0:
        groups = groups_result['stdout'].strip()
        logger.info(f"Группы пользователя: {groups}")
        
        # Проверка наличия группы gpio
        if "gpio" in groups:
            logger.info("Пользователь входит в группу gpio: ДА")
        else:
            logger.warning("Пользователь входит в группу gpio: НЕТ")
    else:
        logger.error(f"Не удалось получить группы для пользователя: {groups_result['stderr']}")

def check_gpio_packages():
    """Проверяет установленные пакеты для работы с GPIO"""
    logger.info("=== Проверка установленных пакетов для GPIO ===")
    
    # Проверка установки RPi.GPIO
    try:
        import RPi.GPIO
        version = RPi.GPIO.VERSION
        logger.info(f"RPi.GPIO: УСТАНОВЛЕН (версия {version})")
    except ImportError:
        logger.warning("RPi.GPIO: НЕ УСТАНОВЛЕН")
    except Exception as e:
        logger.error(f"Ошибка при проверке RPi.GPIO: {str(e)}")
    
    # Проверка установки gpiozero
    try:
        import gpiozero
        version = gpiozero.__version__
        logger.info(f"gpiozero: УСТАНОВЛЕН (версия {version})")
    except ImportError:
        logger.warning("gpiozero: НЕ УСТАНОВЛЕН")
    except Exception as e:
        logger.error(f"Ошибка при проверке gpiozero: {str(e)}")
    
    # Проверка установки wiringpi
    wiringpi_result = run_command("gpio -v")
    if wiringpi_result['returncode'] == 0:
        logger.info("wiringPi: УСТАНОВЛЕН")
    else:
        logger.warning("wiringPi: НЕ УСТАНОВЛЕН или ошибка запуска")

def check_loaded_modules():
    """Проверяет загруженные модули ядра для GPIO"""
    logger.info("=== Проверка загруженных модулей ядра для GPIO ===")
    
    # Проверка модулей связанных с gpio
    gpio_modules = run_command("lsmod | grep -E 'gpio|i2c|spi'")
    if gpio_modules['stdout']:
        logger.info(f"Загруженные модули для GPIO:\n{gpio_modules['stdout']}")
    else:
        logger.warning("Не найдены загруженные модули для GPIO")

def check_gpio_permissions():
    """Проверяет права доступа к GPIO устройствам"""
    logger.info("=== Проверка прав доступа к GPIO устройствам ===")
    
    # Проверка /dev/gpiomem
    if os.path.exists("/dev/gpiomem"):
        gpiomem_result = run_command("ls -la /dev/gpiomem")
        logger.info(f"Права доступа к /dev/gpiomem:\n{gpiomem_result['stdout']}")
    else:
        logger.warning("Устройство /dev/gpiomem не найдено")
    
    # Проверка /dev/gpio
    if os.path.exists("/dev/gpio"):
        gpio_result = run_command("ls -la /dev/gpio")
        logger.info(f"Права доступа к /dev/gpio:\n{gpio_result['stdout']}")
    else:
        logger.info("Устройство /dev/gpio не найдено (это нормально)")
    
    # Проверка /sys/class/gpio
    if os.path.exists("/sys/class/gpio"):
        sysfs_result = run_command("ls -la /sys/class/gpio")
        logger.info(f"Содержимое /sys/class/gpio:\n{sysfs_result['stdout']}")
    else:
        logger.warning("Директория /sys/class/gpio не найдена")

def check_kernel_version():
    """Проверяет версию ядра Linux"""
    logger.info("=== Проверка версии ядра ===")
    kernel_version = platform.uname().release
    logger.info(f"Версия ядра: {kernel_version}")

def try_simple_gpio_test():
    """Пытается провести простой тест GPIO без обработчиков событий"""
    logger.info("=== Простой тест GPIO без обработчиков событий ===")
    
    try:
        import RPi.GPIO as GPIO
        
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        
        # Проверим несколько пинов без настройки обработчиков событий
        test_pins = [17, 27, 22]
        
        for pin in test_pins:
            try:
                # Настраиваем как вход
                GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
                state = GPIO.input(pin)
                logger.info(f"Пин GPIO{pin}: настроен как вход, состояние = {state}")
                
                # Попробуем настроить как выход и установить значение
                GPIO.setup(pin, GPIO.OUT)
                GPIO.output(pin, GPIO.HIGH)
                logger.info(f"Пин GPIO{pin}: настроен как выход, установлен HIGH")
                time.sleep(0.1)
                GPIO.output(pin, GPIO.LOW)
                logger.info(f"Пин GPIO{pin}: установлен LOW")
                time.sleep(0.1)
                GPIO.output(pin, GPIO.HIGH)
                logger.info(f"Пин GPIO{pin}: установлен HIGH")
                
                # Возвращаем как вход
                GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
                logger.info(f"Пин GPIO{pin}: вернули как вход")
                
            except Exception as e:
                logger.error(f"Ошибка при тестировании пина GPIO{pin}: {str(e)}")
        
        GPIO.cleanup()
        logger.info("Простой тест GPIO завершен")
        
    except ImportError:
        logger.error("Не удалось импортировать модуль RPi.GPIO")
    except Exception as e:
        logger.error(f"Ошибка при выполнении простого теста GPIO: {str(e)}")
        try:
            GPIO.cleanup()
        except:
            pass

def run_diagnostics():
    """Запускает полную диагностику GPIO"""
    logger.info("=== Начало диагностики GPIO ===")
    
    # Проверка, запущен ли скрипт с правами root
    if os.geteuid() != 0:
        logger.warning("Скрипт не запущен с правами root (sudo). Некоторые проверки могут не работать.")
    
    # Запуск всех проверок
    check_kernel_version()
    check_raspi_config()
    check_gpio_group()
    check_gpio_packages()
    check_loaded_modules()
    check_gpio_permissions()
    try_simple_gpio_test()
    
    logger.info("=== Диагностика GPIO завершена ===")

if __name__ == "__main__":
    try:
        run_diagnostics()
    except KeyboardInterrupt:
        logger.info("Диагностика прервана пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка при диагностике: {str(e)}")
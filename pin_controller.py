import RPi.GPIO as GPIO
import threading
import time
import logging
from config import logger

class PinController:
    def __init__(self, pin, callback=None, up_down=GPIO.PUD_UP, react_on=GPIO.BOTH, before_callback=None, bouncetime=0.3):
        """
        Инициализация контроллера пина GPIO
        
        :param pin: Номер пина GPIO в формате BCM
        :param callback: Функция обратного вызова при изменении состояния пина
        :param up_down: Режим подтяжки: GPIO.PUD_UP или GPIO.PUD_DOWN
        :param react_on: На какие события реагировать: GPIO.RISING, GPIO.FALLING, GPIO.BOTH
        :param before_callback: Функция обратного вызова перед основным callback
        :param bouncetime: Время для подавления дребезга контактов в секундах (было в мс, теперь в сек)
        """
        # Валидация пина
        self.pin = self._validate_pin(pin)
        self.callback = callback if callback else self._dummy_callback
        self.before_callback = before_callback if before_callback else self._dummy_callback
        self.bounce_time = bouncetime
        self.react_on = react_on
        self.up_down = up_down
        self.state = None
        self.last_state = None
        self.running = False
        self.thread = None
        
        # Настройка GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.pin, GPIO.IN, pull_up_down=self.up_down)
        
        # Сохраняем начальное состояние
        self.state = GPIO.input(self.pin)
        self.last_state = self.state
        
        logger.info(f"Инициализирован пин GPIO{self.pin}, начальное состояние: {self.state}")
        
        # Запускаем мониторинг пина в отдельном потоке
        self.start_monitoring()
    
    def _validate_pin(self, pin):
        """Проверка корректности номера пина"""
        if not pin:
            raise Exception("Pin number expected.")
        if not isinstance(pin, str) and not isinstance(pin, int):
            raise Exception("Integer expected")
        if isinstance(pin, str) and not pin.isdigit():
            raise Exception("Integer expected")
        pin = int(pin)
        if pin < 0 or 27 < pin:
            raise Exception("BCM mode provide numbers [0; 27]. {} given.".format(pin))
        return pin
    
    def _dummy_callback(self, *args):
        """Пустая функция обратного вызова"""
        pass
    
    def start_monitoring(self):
        """Запуск мониторинга пина в отдельном потоке"""
        self.running = True
        self.thread = threading.Thread(target=self._monitor_pin)
        self.thread.daemon = True
        self.thread.start()
        logger.info(f"Мониторинг пина GPIO{self.pin} запущен")
    
    def stop_monitoring(self):
        """Остановка мониторинга пина"""
        self.running = False
        if self.thread:
            self.thread.join(1.0)
        logger.info(f"Мониторинг пина GPIO{self.pin} остановлен")
    
    def _monitor_pin(self):
        """Функция мониторинга пина, работающая в отдельном потоке"""
        last_time = time.time()
        
        while self.running:
            current_state = GPIO.input(self.pin)
            current_time = time.time()
            
            # Если состояние изменилось и прошло достаточно времени (для дребезга)
            if current_state != self.last_state and (current_time - last_time) > self.bounce_time:
                # Проверка на тип события
                if (self.react_on == GPIO.BOTH or 
                    (self.react_on == GPIO.RISING and current_state == 1) or 
                    (self.react_on == GPIO.FALLING and current_state == 0)):
                    
                    self.state = current_state
                    # Вызов before_callback
                    self.before_callback(self)
                    # Вызов основного callback
                    self.callback(self)
                    
                    logger.info(f"Изменение на пине GPIO{self.pin}: {current_state}")
                
                self.last_state = current_state
                last_time = current_time
            
            # Небольшая задержка для уменьшения нагрузки на CPU
            time.sleep(0.01)
    
    def check_pin(self):
        """Проверка текущего состояния пина"""
        current_state = GPIO.input(self.pin)
        if current_state != self.state:
            self.state = current_state
            logger.info(f"Обновлено состояние пина GPIO{self.pin}: {self.state}")
        return self.state
    
    def read(self):
        """Прочитать текущее состояние пина"""
        return GPIO.input(self.pin)
    
    def cleanup(self):
        """Освободить ресурсы"""
        self.stop_monitoring()
        # Не очищаем GPIO здесь, чтобы другие контроллеры могли использовать его
import RPi.GPIO as GPIO
import time
import threading
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class PinController:
    def __init__(self, pin, pull_up=True, bounce_time=0.3):
        self.pin = pin
        self.pull_up = pull_up
        self.bounce_time = bounce_time
        self.last_state = None
        self.callback = None
        self.running = False
        self.thread = None
        
        # Настройка GPIO
        GPIO.setmode(GPIO.BCM)
        if pull_up:
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        else:
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
        
        # Сохраняем начальное состояние
        self.last_state = GPIO.input(pin)
        
        logger.info(f"Инициализирован пин GPIO{pin}, начальное состояние: {self.last_state}")
    
    def start_monitoring(self):
        self.running = True
        self.thread = threading.Thread(target=self._monitor_pin)
        self.thread.daemon = True
        self.thread.start()
        logger.info(f"Мониторинг пина GPIO{self.pin} запущен")
    
    def stop_monitoring(self):
        self.running = False
        if self.thread:
            self.thread.join(1.0)
        logger.info(f"Мониторинг пина GPIO{self.pin} остановлен")
    
    def _monitor_pin(self):
        last_time = time.time()
        
        while self.running:
            current_state = GPIO.input(self.pin)
            current_time = time.time()
            
            # Если состояние изменилось и прошло достаточно времени (для дребезга)
            if current_state != self.last_state and (current_time - last_time) > self.bounce_time:
                if self.callback:
                    self.callback(self.pin, current_state)
                logger.info(f"Изменение на пине GPIO{self.pin}: {current_state}")
                
                self.last_state = current_state
                last_time = current_time
            
            # Небольшая задержка для уменьшения нагрузки на CPU
            time.sleep(0.01)
    
    def set_callback(self, callback):
        """Установить функцию обратного вызова при изменении состояния пина"""
        self.callback = callback
    
    def read(self):
        """Прочитать текущее состояние пина"""
        return GPIO.input(self.pin)
    
    def cleanup(self):
        """Освободить ресурсы"""
        self.stop_monitoring()
        # Не очищаем GPIO здесь, чтобы другие контроллеры могли использовать его

def pin_changed(pin, state):
    logger.info(f"Callback: Пин GPIO{pin} изменил состояние на {state}")

# Пример использования
if __name__ == "__main__":
    try:
        # Список пинов для тестирования
        pins = [17, 27, 22, 10, 9, 11, 5, 6, 13, 19, 26]
        controllers = []
        
        logger.info(f"Тестирование {len(pins)} пинов")
        
        for pin in pins:
            try:
                controller = PinController(pin)
                controller.set_callback(pin_changed)
                controller.start_monitoring()
                controllers.append(controller)
                logger.info(f"Пин GPIO{pin} успешно настроен")
            except Exception as e:
                logger.error(f"Ошибка при настройке пина GPIO{pin}: {str(e)}")
        
        # Даем время для работы мониторинга
        logger.info("Мониторинг запущен, нажмите Ctrl+C для завершения...")
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Тестирование остановлено пользователем")
    finally:
        # Освобождаем ресурсы
        for controller in controllers:
            controller.cleanup()
        GPIO.cleanup()
        logger.info("GPIO освобождены")
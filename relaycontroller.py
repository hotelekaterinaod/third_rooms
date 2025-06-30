import smbus
import threading
import time

class RelayController:
    """
    Улучшенный контроллер реле с предотвращением дребезга и кэшированием состояний
    """
    _instances = {}  # Хранение всех экземпляров по адресам
    _locks = {}      # Мьютексы для каждого адреса
    
    def __init__(self, address, bus_num=1):
        """
        Инициализация контроллера реле
        
        Args:
            address: I2C адрес контроллера
            bus_num: Номер I2C шины (по умолчанию 1)
        """
        self.address = address
        self.bus_num = bus_num
        
        # Создаем мьютекс для этого адреса, если его еще нет
        if address not in RelayController._locks:
            RelayController._locks[address] = threading.Lock()
        
        # Сохраняем экземпляр в глобальном словаре
        RelayController._instances[address] = self
        
        try:
            self.bus = smbus.SMBus(bus_num)
            # Инициализация: читаем текущее состояние и кэшируем его
            with RelayController._locks[address]:
                self._state = self.bus.read_byte(address)
        except Exception as e:
            # Если устройство недоступно, предполагаем, что все биты установлены в 1
            self._state = 0xFF
            self.device_available = False
            print(f"Warning: RelayController at address 0x{address:02X} is not available: {str(e)}")
        else:
            self.device_available = True
    
    def set_bit(self, bit, debounce_ms=0):
        """
        Установить бит (установить в 1), не влияя на другие биты
        
        Args:
            bit: номер бита (0-7)
            debounce_ms: задержка для предотвращения дребезга в миллисекундах
        
        Returns:
            bool: True, если операция выполнена успешно
        """
        if not self.device_available:
            return False
            
        if not 0 <= bit <= 7:
            raise ValueError("Bit must be between 0 and 7")
        
        # Используем мьютекс для атомарной операции
        with RelayController._locks[self.address]:
            # Вычисляем новое состояние: устанавливаем бит в 1
            new_state = self._state | (1 << bit)
            
            # Если состояние не изменилось, ничего не делаем
            if new_state == self._state:
                return True
            
            try:
                # Записываем новое состояние
                self.bus.write_byte(self.address, new_state)
                
                # Задержка для предотвращения дребезга
                if debounce_ms > 0:
                    time.sleep(debounce_ms / 1000.0)
                
                # Обновляем кэшированное состояние
                self._state = new_state
                return True
            except Exception as e:
                print(f"Error setting bit {bit} on relay at 0x{self.address:02X}: {str(e)}")
                return False
    
    def clear_bit(self, bit, debounce_ms=0):
        """
        Очистить бит (установить в 0), не влияя на другие биты
        
        Args:
            bit: номер бита (0-7)
            debounce_ms: задержка для предотвращения дребезга в миллисекундах
        
        Returns:
            bool: True, если операция выполнена успешно
        """
        if not self.device_available:
            return False
            
        if not 0 <= bit <= 7:
            raise ValueError("Bit must be between 0 and 7")
        
        # Используем мьютекс для атомарной операции
        with RelayController._locks[self.address]:
            # Вычисляем новое состояние: устанавливаем бит в 0
            new_state = self._state & ~(1 << bit)
            
            # Если состояние не изменилось, ничего не делаем
            if new_state == self._state:
                return True
            
            try:
                # Записываем новое состояние
                self.bus.write_byte(self.address, new_state)
                
                # Задержка для предотвращения дребезга
                if debounce_ms > 0:
                    time.sleep(debounce_ms / 1000.0)
                
                # Обновляем кэшированное состояние
                self._state = new_state
                return True
            except Exception as e:
                print(f"Error clearing bit {bit} on relay at 0x{self.address:02X}: {str(e)}")
                return False
    
    def get_bit(self, bit):
        """
        Получить состояние бита (0 или 1)
        
        Args:
            bit: номер бита (0-7)
            
        Returns:
            int: 0 или 1, состояние указанного бита
        """
        if not self.device_available:
            return 1  # По умолчанию, если устройство недоступно
            
        if not 0 <= bit <= 7:
            raise ValueError("Bit must be between 0 and 7")
        
        # Используем кэшированное состояние
        return 1 if (self._state & (1 << bit)) else 0
    
    def get_state(self):
        """
        Получить текущее состояние всех битов
        
        Returns:
            int: байт состояния (0-255)
        """
        if not self.device_available:
            return self._state
        
        # Для свежих данных можно перечитать с устройства
        with RelayController._locks[self.address]:
            try:
                self._state = self.bus.read_byte(self.address)
            except Exception as e:
                print(f"Error reading state from relay at 0x{self.address:02X}: {str(e)}")
                
        return self._state
    
    def reset_all(self):
        """
        Сбросить все биты (установить в 1)
        
        Returns:
            bool: True, если операция выполнена успешно
        """
        if not self.device_available:
            return False
            
        # Используем мьютекс для атомарной операции
        with RelayController._locks[self.address]:
            try:
                # Устанавливаем все биты в 1
                self.bus.write_byte(self.address, 0xFF)
                
                # Задержка для стабилизации
                time.sleep(0.1)
                
                # Обновляем кэшированное состояние
                self._state = 0xFF
                return True
            except Exception as e:
                print(f"Error resetting all bits on relay at 0x{self.address:02X}: {str(e)}")
                return False
    
    @classmethod
    def get_controller(cls, address, bus_num=1):
        """
        Получить существующий экземпляр контроллера или создать новый
        
        Args:
            address: I2C адрес контроллера
            bus_num: Номер I2C шины (по умолчанию 1)
        
        Returns:
            RelayController: экземпляр контроллера
        """
        if address in cls._instances:
            return cls._instances[address]
        else:
            return cls(address, bus_num)
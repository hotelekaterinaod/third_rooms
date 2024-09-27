import serial
from config import system_config, logger

def wait_for_rfid(port='/dev/ttyS0', baudrate=9600, timeout=1):
    try:

        while True:
            rfid_port = serial.Serial(port, baudrate, timeout=timeout)
            print(f"Listening for RFID on {port}")
            read_byte = (rfid_port.read(system_config.rfid_key_length)[1:11])
            key_ = read_byte.decode("utf-8")
            rfid_port.close()
            if key_:
                logger.info("key catched {key} {datetime}".format(key=key_, datetime=datetime.utcnow()))
                return key_
            else:
                logger.info(f"No key {key_}")
    except serial.SerialException as e:
        print(f"Serial error: {e}")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        rfid_port.close()

if __name__ == "__main__":
    wait_for_rfid()





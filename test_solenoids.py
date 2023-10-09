#! /usr/bin/env python
# -*- coding: utf-8 -*-
import threading
import time
import signal
import smbus
from datetime import datetime, timedelta
import pymssql
import serial
import RPi.GPIO as GPIO
from retry import retry
import logging
import asyncio

from pin_controller import PinController
from relaycontroller import RelayController
from config import system_config, logger



db_connection = None

bus = smbus.SMBus(1)

# адреса контроллеров
relay1_controller = RelayController(0x38)



print("Set bit")
relay1_controller.set_bit(3)  # соленоиды
time.sleep(3)
print("After 3 sec clear bit")
relay1_controller.clear_bit(3)  # соленоиды
time.sleep(3)
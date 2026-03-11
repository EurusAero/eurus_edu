import json
import socket
import os
from .const import *

class MessagesUtils:
    def __init__(self):
        pass

    def __compare_keys(self, msg, command):
        if msg.keys() == MESSAGES[command].keys():
            return True
        for key in msg.keys():
            if key not in MESSAGES[command].keys():
                raise KeyError(f"Ключа '{key}' не cуществует в сообщении '{command}'")
    
    def __compare_types(self, msg, command):
        for key in msg.keys():
            if not isinstance(msg[key], MESSAGES[command][key]):
                raise TypeError(f"Тип данных ключа '{key}' не соответствует требуемому типу данных")
        return True
    
    def __compare_data(self, msg, command):
        if command not in MESSAGES.keys():
            raise ValueError(f"Команда '{command}' не существует")
        for key in msg.keys():
            if msg[key] == float("inf") or msg[key] == float("-inf"):
                raise ValueError(f"Значение ключа '{key}' не может быть бесконечностью")
        return True
            
    def validate_message(self, message):
        if not isinstance(message, dict):
            raise TypeError("Тип данных сообщения не является словарём")
        
        if "command" in message.keys():
            if self.__compare_data(message, message["command"]) and \
               self.__compare_keys(message, message["command"]) and \
               self.__compare_types(message, message["command"]):
                return True
        else:
            raise KeyError("В сообщении отсутствует ключ 'command'")
        return None


class SocketsUtils:
    def __init__(self):
        # Конвертируем маркеры в байты сразу при инициализации
        self.start_marker = START_MARKER.encode('utf-8')
        self.end_marker = END_MARKER.encode('utf-8')

    def send_json(self, conn: socket.socket, data_dict: dict):
        """
        Упаковывает словарь в JSON, оборачивает маркерами и отправляет в сокет.
        """
        try:
            response_json = json.dumps(data_dict)
            packet = self.start_marker + response_json.encode('utf-8') + self.end_marker
            conn.sendall(packet)
        except Exception as e:
            # Пробрасываем ошибку выше, чтобы логгер в сервере её поймал
            raise e

    def parse_buffer(self, buffer: bytes):
        """
        Ищет полные сообщения в буфере.
        Возвращает кортеж: (список_найденных_сообщений, остаток_буфера)
        """
        messages = []
        
        while True:
            start_index = buffer.find(self.start_marker)
            end_index = buffer.find(self.end_marker, start_index) if start_index != -1 else -1

            if start_index != -1 and end_index != -1:
                payload = buffer[start_index + len(self.start_marker) : end_index]
                
                buffer = buffer[end_index + len(self.end_marker):]
                
                try:
                    decoded_msg = payload.decode('utf-8')
                    messages.append(decoded_msg)
                except UnicodeDecodeError:
                    messages.append(None) 
            else:
                break
        
        return messages, buffer
    
    
class GpioController:
    BASE_PATH = "/sys/class/gpio"

    def __init__(self, pin_number):
        """
        :param pin_number: Номер GPIO пина в sysfs
        """
        self.pin = str(pin_number)
        self.pin_path = os.path.join(self.BASE_PATH, f"gpio{self.pin}")

    def export(self):
        """Активирует пин"""
        if not os.path.exists(self.pin_path):
            try:
                with open(os.path.join(self.BASE_PATH, "export"), 'w') as f:
                    f.write(self.pin)
            except OSError as e:
                raise Exception(f"Error exporting pin {self.pin}: {e}")

    def set_mode(self, mode):
        """
        Установка режима: 'in' (вход) или 'out' (выход)
        """
        direction_path = os.path.join(self.pin_path, "direction")
        try:
            with open(direction_path, 'w') as f:
                f.write(mode)
        except OSError as e:
            raise Exception(f"Error setting mode for pin {self.pin}: {e}")

    def write(self, value):
        """
        Запись значения: 1 (High) или 0 (Low)
        """
        value_path = os.path.join(self.pin_path, "value")
        val_str = "1" if value else "0"
        try:
            with open(value_path, 'w') as f:
                f.write(val_str)
        except OSError as e:
            raise Exception(f"Error writing to pin {self.pin}: {e}")
    
    def read(self):
        value_path = os.path.join(self.pin_path, "value")
        try:
            with open(value_path, 'r') as f:
                return int(f.readline().strip())
        except OSError as e:
            raise Exception(f"Error writing to pin {self.pin}: {e}")

    def cleanup(self):
        """Освобождает пин (unexport)"""
        if os.path.exists(self.pin_path):
            try:
                with open(os.path.join(self.BASE_PATH, "unexport"), 'w') as f:
                    f.write(self.pin)
            except OSError:
                pass
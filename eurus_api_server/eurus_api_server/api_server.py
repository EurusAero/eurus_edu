import socket
import json
import threading
import configparser
import logging
import os

from EurusEdu.utils import MessagesUtils, SocketsUtils
from EurusEdu.const import *

import rclpy
from rclpy.node import node
from eurus_msgs.msg import Command

config = configparser.ConfigParser()
config_path = '/home/orangepi/ros2_ws/src/eurus_edu/eurus_api_server/eurus.ini'

if os.path.exists(config_path):
    config.read(config_path)
    HOST = config['SERVER']['HOST']
    PORT = int(config['SERVER']['PORT'])
    BUFFER_SIZE = int(config['SERVER']['BUFFER_SIZE'])
    LOG_LEVEL = config['LOGGING']['LEVEL'].upper()
    LOG_FILE = config['LOGGING'].get('FILE', None)

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.DEBUG),
    format='[SERVER] [%(asctime)s] [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE) if LOG_FILE else logging.NullHandler(),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("EurusServer")

class CommandPublisher(Node):
    def __init__(self):
        self.publisher_ = self.create_publisher(Command, 'topic', 10)
        
        self.is_busy = False
    
    def publish_new_command(self, command_name: str, data: dict):
        if self.is_busy:
            return False
        
        msg = Command()
        
        

class CommandHandler:
    """
    Класс, ответственный за выполнение команд.
    Сюда мы передаем JSON, и здесь будет жить логика управления железом.
    """
    def __init__(self, session):
        self.session = session  # Ссылка на сессию, чтобы отправлять ответы

    def handle(self, message: dict):
        """
        Главный метод обработки.
        Сейчас это ЗАГЛУШКА: мы просто отказываем в выполнении.
        """
        command = message.get("command")
        logger.debug(f"CommandHandler получил команду: {command}")

        # --- ЗАГЛУШКА ---
        # Так как реализация железа еще не готова, мы шлем отказ.
        # Для команд движения (takeoff, land, goto) клиент ждет action_complete.
        
        response = {
            "command": "action_status",
            "action": command,
            "code": CODE_DENIED, # 400
            "message": "Not implemented yet (Server Stub)"
        }
        
        # Если это запрос телеметрии, клиент ждет response_telemetry,
        # но пока мы тоже можем вернуть ошибку или пустую телеметрию.
        if command == "request_telemetry":
            response = {
                "command": "response_telemetry",
                "telemetry": {} # Пустая телеметрия
            }

        # Отправляем ответ клиенту
        self.session.send_json(response)


class ClientSession:
    """
    Класс, обслуживающий соединение.
    Занимается только чтением, валидацией и передачей команд в Handler.
    """
    def __init__(self, conn, addr):
        self.conn = conn
        self.addr = addr
        self.sock_utils = SocketsUtils()
        self.msg_utils = MessagesUtils()
        
        # Инициализируем обработчик команд
        self.command_handler = CommandHandler(self)
        
        self.socket_lock = threading.Lock()

    def start(self):
        logger.info(f"Сессия начата для {self.addr}")
        buffer = b""
        
        try:
            while True:
                chunk = self.conn.recv(BUFFER_SIZE)
                if not chunk:
                    break
                
                buffer += chunk
                messages, buffer = self.sock_utils.parse_buffer(buffer)
                
                for msg_str in messages:
                    if msg_str:
                        self._process_request(msg_str)
                        
        except ConnectionResetError:
            logger.info(f"Клиент {self.addr} разорвал соединение.")
        except Exception as e:
            logger.error(f"Ошибка сессии {self.addr}: {e}", exc_info=True)
        finally:
            self.conn.close()
            logger.info(f"Сессия завершена для {self.addr}")

    def send_json(self, data):
        """Публичный метод для отправки данных (используется CommandHandler-ом)."""
        with self.socket_lock:
            try:
                self.sock_utils.send_json(self.conn, data)
            except Exception as e:
                logger.error(f"Не удалось отправить данные {self.addr}: {e}")

    def _process_request(self, json_data):
        """
        Валидация и передача управления в CommandHandler.
        """
        try:
            message = json.loads(json_data)
            
            # 1. Валидация структуры (utils)
            self.msg_utils.validate_message(message)
            
            # 2. Мгновенный ответ (ACK) - "Я тебя услышал"
            self.send_json({
                "command": "response",
                "status": "success",
                "message": "Command received"
            })
            
            
            threading.Thread(
                target=self.command_handler.handle,
                args=(message,),
                daemon=True
            ).start()

        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            logger.warning(f"Ошибка валидации от {self.addr}: {e}")
            self.send_json({
                "command": "response",
                "status": "error",
                "message": str(e)
            })


def start_server():
    logger.info(f"Запуск сервера EurusEdu на {HOST}:{PORT}...")
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        server.bind((HOST, PORT))
        server.listen()
        logger.info("Сервер готов и ожидает подключений.")

        while True:
            conn, addr = server.accept()
            session = ClientSession(conn, addr)
            
            thread = threading.Thread(target=session.start)
            thread.daemon = True
            thread.start()
            
            logger.debug(f"Активных клиентов: {threading.active_count() - 1}")

    except KeyboardInterrupt:
        logger.info("\nОстановка сервера...")
    except Exception as e:
        logger.critical(f"Критическая ошибка сервера: {e}", exc_info=True)
    finally:
        server.close()

if __name__ == "__main__":
    start_server()
import socket
import json
import threading
import configparser
import logging
import os
import time

from EurusEdu.utils import MessagesUtils, SocketsUtils
from EurusEdu.const import *

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy

from edu_msgs.msg import Command, Telemetry

config = configparser.ConfigParser()
config_path = '/home/orangepi/ros2_ws/src/eurus_edu/edu_api_server/eurus.ini'

if os.path.exists(config_path):
    config.read(config_path)
    HOST = config['server'].get('host')
    PORT = int(config['server'].get('port'))
    BUFFER_SIZE = int(config['server'].get('buffer_size'))
    LOG_LEVEL = config['logging'].get('level', 'DEBUG').upper()
    LOG_FILE = config['logging'].get('file', None)

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.DEBUG),
    format='[SERVER] [%(asctime)s] [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE) if LOG_FILE else logging.NullHandler(),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("EurusServer")


class EduApiNode(Node):
    """
    ROS 2 Node, который связывает TCP сервер с экосистемой ROS.
    """
    def __init__(self):
        super().__init__('edu_api_server')
        
        qos_profile = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10
        )

        # Публикация команд (отправляем pending)
        self.cmd_pub = self.create_publisher(Command, 'edu/command', qos_profile)
        
        # Подписка на изменение статуса команд (от контроллера)
        self.status_sub = self.create_subscription(
            Command, 
            'edu/command', 
            self.command_status_callback, 
            qos_profile
        )
        
        # Подписка на телеметрию
        self.telemetry_sub = self.create_subscription(
            Telemetry,
            'edu/telemetry',
            self.telemetry_callback,
            qos_profile
        )

        self.is_busy = False
        self.current_command_id = 0.0
        self.current_command_name = None
        
        self.latest_telemetry = {}
        
        self.active_session = None
        self.session_lock = threading.Lock()

    def set_active_session(self, session):
        with self.session_lock:
            self.active_session = session

    def remove_active_session(self, session):
        with self.session_lock:
            if self.active_session == session:
                self.active_session = None

    def telemetry_callback(self, msg: Telemetry):
        """Обновляем кэш телеметрии из топика."""
        try:
            data = json.loads(msg.data)
            self.latest_telemetry = data
        except json.JSONDecodeError:
            logger.error("Получена некорректная JSON телеметрия из ROS топика")

    def command_status_callback(self, msg: Command):
        """
        Коллбек, когда контроллер обновляет статус команды.
        Здесь мы проверяем статус и отправляем ответ клиенту TCP.
        """
        if not self.is_busy or abs(msg.timestamp - self.current_command_id) > 0.0001:
            return

        status = msg.status
        logger.info(f"Обновление статуса команды '{msg.command}': {status}")

        response_data = {
            "command": "action_status",
            "action": msg.command,
            "status": status,
            "message": msg.data
        }

        # Отправляем клиенту
        with self.session_lock:
            if self.active_session:
                self.active_session.send_json(response_data)

        # Логика разблокировки
        if status in [COMPLETED_STATUS, DENIED_STATUS]:
            self.is_busy = False
            self.current_command_name = None
            logger.info(f"Поток команд разблокирован. Команда '{msg.command}' завершена со статусом {status}.")
        
        elif status == RUNNING_STATUS:
            # Просто информируем, блокировку не снимаем
            pass

    def process_client_command(self, request_msg: dict, session):
        """
        Обработка входящего JSON от клиента.
        Возвращает ответ (словарь), который нужно отправить немедленно (ACK или Telemetry).
        """
        cmd_name = request_msg.get("command")
        
        if cmd_name == "request_telemetry":
            return {
                "command": "response_telemetry",
                "telemetry": self.latest_telemetry
            }

        if cmd_name in DRONE_COMMANDS:
            if self.is_busy:
                return {
                    "command": "action_status",
                    "action": cmd_name,
                    "status": DENIED_STATUS,
                    "message": f"Server busy executing: {self.current_command_name}"
                }
            
            self.is_busy = True
            self.current_command_name = cmd_name
            self.current_command_id = time.time()
            self.set_active_session(session)

            ros_msg = Command()
            ros_msg.timestamp = self.current_command_id
            ros_msg.command = cmd_name
            ros_msg.status = PENDING_STATUS
            
            data_payload = {k: v for k, v in request_msg.items() if k != "command"}
            ros_msg.data = json.dumps(data_payload)
            
            self.cmd_pub.publish(ros_msg)
            logger.info(f"Опубликована команда в ROS: {cmd_name}, ID: {self.current_command_id}")

            return {
                "command": "action_status",
                "action": cmd_name,
                "status": PENDING_STATUS,
                "message": "Command sent to controller"
            }

        return {
            "command": "response",
            "status": "error",
            "message": f"Unknown command: {cmd_name}"
        }
    
    def force_land(self):
        msg = Command()
        msg.timestamp = time.time()
        msg.command = "land"
        msg.status = PENDING_STATUS
        msg.data = ""
        
        self.cmd_pub.publish(msg)
        self.is_busy = False


class ClientSession:
    """
    Класс сессии TCP.
    """
    def __init__(self, conn, addr, ros_node: EduApiNode):
        self.conn = conn
        self.addr = addr
        self.ros_node = ros_node
        
        self.sock_utils = SocketsUtils()
        self.msg_utils = MessagesUtils()
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
                        self._handle_request(msg_str)
                        
        except ConnectionResetError:
            logger.info(f"Клиент {self.addr} разорвал соединение.")
        except Exception as e:
            logger.error(f"Ошибка сессии {self.addr}: {e}", exc_info=True)
        finally:
            self.ros_node.force_land()
            self.ros_node.remove_active_session(self)
            self.conn.close()
            logger.info(f"Сессия завершена для {self.addr}")

    def send_json(self, data):
        """Отправка JSON клиенту (потокобезопасно)."""
        with self.socket_lock:
            try:
                self.sock_utils.send_json(self.conn, data)
                # logger.debug(f"Отправлено клиенту {self.addr}: {data.get('command')}")
            except Exception as e:
                logger.error(f"Не удалось отправить данные {self.addr}: {e}")

    def _handle_request(self, json_data):
        try:
            message = json.loads(json_data)
            
            self.msg_utils.validate_message(message)
            
            if message.get("command") != "request_telemetry":
                self.send_json({
                    "command": "response",
                    "status": "success",
                    "message": "received"
                })

            result = self.ros_node.process_client_command(message, self)
            
            if result:
                self.send_json(result)

        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            logger.warning(f"Ошибка обработки от {self.addr}: {e}")
            self.send_json({
                "command": "response",
                "status": "error",
                "message": str(e)
            })


def start_server():
    rclpy.init()
    edu_node = EduApiNode()
    
    ros_thread = threading.Thread(target=rclpy.spin, args=(edu_node,), daemon=True)
    ros_thread.start()

    logger.info(f"Запуск TCP сервера EurusEdu на {HOST}:{PORT}...")
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    active_client_thread = None

    try:
        server.bind((HOST, PORT))
        server.listen()

        while True:
            conn, addr = server.accept()

            if active_client_thread is not None and active_client_thread.is_alive():
                logger.warning(f"Входящее соединение от {addr} отклонено: сервер занят другим клиентом.")
                conn.close()
                continue
            
            session = ClientSession(conn, addr, edu_node)
            
            active_client_thread = threading.Thread(target=session.start)
            active_client_thread.daemon = True
            active_client_thread.start()
            
            logger.info(f"Клиент {addr} принят.")

    except KeyboardInterrupt:
        logger.info("\nОстановка сервера...")
    except Exception as e:
        logger.critical(f"Критическая ошибка сервера: {e}", exc_info=True)
    finally:
        server.close()
        try:
            edu_node.destroy_node()
            rclpy.shutdown()
        except Exception:
            pass

if __name__ == "__main__":
    start_server()
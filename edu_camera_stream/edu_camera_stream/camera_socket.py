import socket
import json
import threading
import configparser
import logging
import os
import time
import base64

from EurusEdu.utils import MessagesUtils, SocketsUtils
from EurusEdu.const import *

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String

config = configparser.ConfigParser()
config_path = '/home/orangepi/ros2_ws/src/eurus_edu/edu_camera_stream/eurus.ini'

HOST = '0.0.0.0'
PORT = 8001
BUFFER_SIZE = 4096
LOG_LEVEL = 'INFO'
LOG_FILE = None
FPS = 30

if os.path.exists(config_path):
    config.read(config_path)
    if 'server' in config:
        HOST = config['server'].get('host', HOST)
        PORT = config['server'].getint('port', PORT)
    if 'camera' in config:
        FPS = config['camera'].getint('fps', FPS)
    if 'logging' in config:
        LOG_LEVEL = config['logging'].get('level', 'INFO').upper()


logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='[CAM-SERVER] [%(asctime)s] [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE) if LOG_FILE else logging.NullHandler(),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("EurusCamServer")


class CameraBridgeNode(Node):
    """
    ROS 2 Node: Слушает топик с камерой и топик с результатами нейросети.
    """
    def __init__(self):
        super().__init__('edu_camera_server')
        
        qos_profile = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            depth=1
        )

        # Подписка на камеру
        self.sub = self.create_subscription(
            CompressedImage,
            '/edu/camera_frame',
            self.image_callback,
            qos_profile
        )
        
        # Подписка на результаты YOLO
        self.target_sub = self.create_subscription(
            String,
            '/edu/targets',
            self.target_callback,
            10
        )
        
        self.latest_frame_b64 = None
        self.latest_targets = None
        
        self.last_frame_time = 0
        self.lock = threading.Lock()
        
        logger.info("CameraBridgeNode запущен, ожидание кадров и таргетов...")

    def image_callback(self, msg: CompressedImage):
        """Получаем JPEG байты, конвертируем в Base64."""
        try:
            b64_data = base64.b64encode(msg.data).decode('utf-8')
            
            with self.lock:
                self.latest_frame_b64 = b64_data
                self.last_frame_time = time.time()
                
        except Exception as e:
            logger.error(f"Ошибка обработки кадра: {e}")

    def target_callback(self, msg: String):
        """Получаем JSON строку от YOLO ноды."""
        try:
            data = json.loads(msg.data)
            with self.lock:
                self.latest_targets = data
        except json.JSONDecodeError:
            logger.error(f"Получен битый JSON в /edu/targets: {msg.data}")

    def get_frame(self):
        with self.lock:
            return self.latest_frame_b64
            
    def get_targets(self):
        with self.lock:
            return self.latest_targets


class CameraSession:
    """
    Сессия для отправки видео и данных обнаружения.
    """
    def __init__(self, conn, addr, ros_node: CameraBridgeNode):
        self.conn = conn
        self.addr = addr
        self.ros_node = ros_node
        self.sock_utils = SocketsUtils()
        
        self.is_streaming = False
        self.stream_thread = None
        self.socket_lock = threading.Lock()
        self.running = True

    def start(self):
        logger.info(f"Видео-сессия начата для {self.addr}")
        buffer = b""
        
        try:
            while self.running:
                chunk = self.conn.recv(BUFFER_SIZE)
                if not chunk:
                    break
                
                buffer += chunk
                messages, buffer = self.sock_utils.parse_buffer(buffer)
                
                for msg_str in messages:
                    if msg_str:
                        self._process_command(msg_str)
                        
        except (ConnectionResetError, BrokenPipeError):
            logger.info(f"Клиент {self.addr} отключился.")
        except Exception as e:
            logger.error(f"Ошибка сессии {self.addr}: {e}", exc_info=True)
        finally:
            self.stop_stream()
            self.conn.close()
            logger.info(f"Видео-сессия завершена для {self.addr}")

    def send_json(self, data):
        """Потокобезопасная отправка."""
        with self.socket_lock:
            try:
                self.sock_utils.send_json(self.conn, data)
                return True
            except Exception as e:
                logger.error(f"Ошибка отправки данных: {e}")
                self.running = False
                return False

    def _process_command(self, json_data):
        try:
            msg = json.loads(json_data)
            command = msg.get("command")
            
            if command == "get_frame":
                self._send_single_frame()
                
            elif command == "get_stream":
                if not self.is_streaming:
                    self.start_stream()
            
            elif command == "stop_stream":
                self.stop_stream()
                
            elif command == "get_target":
                self._send_targets()

        except json.JSONDecodeError:
            pass

    def _send_single_frame(self):
        frame = self.ros_node.get_frame()
        if frame:
            response = {
                "command": "frame_response",
                "image": frame,
                "timestamp": time.time()
            }
            self.send_json(response)
        else:
            self.send_json({"command": "error", "message": "No frame available"})

    def _send_targets(self):
        targets = self.ros_node.get_targets()
        
        if targets:
            self.send_json(targets)
        else:
            # Если данных от нейросети еще нет, шлем пустой ответ
            empty_response = {
                "command": "targets_response",
                "red_targets": [],
                "blue_targets": [],
                "all_targets": []
            }
            self.send_json(empty_response)

    def start_stream(self):
        self.is_streaming = True
        self.stream_thread = threading.Thread(target=self._stream_loop, daemon=True)
        self.stream_thread.start()
        logger.info("Поток видео запущен.")

    def stop_stream(self):
        self.is_streaming = False
        if self.stream_thread and self.stream_thread.is_alive():
            self.stream_thread.join(timeout=1.0)
        logger.info("Поток видео остановлен.")

    def _stream_loop(self):
        """Цикл отправки кадров."""
        last_loop_time = 0
        interval = 1.0 / FPS
        
        while self.is_streaming and self.running:
            now = time.time()
            
            frame = self.ros_node.get_frame()
            if frame:
                response = {
                    "command": "stream_frame",
                    "image": frame,
                    "timestamp": now
                }
                
                if not self.send_json(response):
                    break
                
            last_loop_time = time.time()
            
            loop_interval = last_loop_time - now
            time.sleep(max(0, (interval - loop_interval)))


def start_server():
    rclpy.init()
    camera_node = CameraBridgeNode()
    
    ros_thread = threading.Thread(target=rclpy.spin, args=(camera_node,), daemon=True)
    ros_thread.start()

    logger.info(f"Запуск CAMERA сервера на {HOST}:{PORT}...")
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    active_thread = None

    try:
        server.bind((HOST, PORT))
        server.listen()
        logger.info("Готов к передаче видео. Разрешен ОДИН клиент.")

        while True:
            conn, addr = server.accept()

            # Single Client Check
            if active_thread is not None and active_thread.is_alive():
                logger.warning(f"Соединение {addr} отклонено (сервер занят).")
                conn.close()
                continue
            
            session = CameraSession(conn, addr, camera_node)
            
            active_thread = threading.Thread(target=session.start)
            active_thread.daemon = True
            active_thread.start()

    except KeyboardInterrupt:
        logger.info("Остановка сервера...")
    except Exception as e:
        logger.critical(f"Ошибка: {e}", exc_info=True)
    finally:
        server.close()
        try:
            camera_node.destroy_node()
            rclpy.shutdown()
        except:
            pass

if __name__ == "__main__":
    start_server()
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

config = configparser.ConfigParser()
config_path = '/home/orangepi/ros2_ws/src/eurus_edu/edu_camera_stream/eurus.ini'

HOST = '0.0.0.0'
PORT = 8001
BUFFER_SIZE = 4096
LOG_LEVEL = 'INFO'
LOG_FILE = None

if os.path.exists(config_path):
    config.read(config_path)
    if 'server' in config:
        HOST = config['server'].get('host', HOST)
        PORT = int(config['camera_server'].get('port', 8001)) if 'camera_server' in config else 8001
    
    if 'LOGGING' in config:
        LOG_LEVEL = config['LOGGING'].get('LEVEL', 'INFO').upper()
        LOG_FILE = config['LOGGING'].get('FILE_CAMERA', None)

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
    ROS 2 Node: Слушает топик с камерой и сохраняет последний кадр.
    """
    def __init__(self):
        super().__init__('edu_camera_server')
        
        # QoS должен совпадать с паблишером (BEST_EFFORT)
        qos_profile = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            depth=1
        )

        self.sub = self.create_subscription(
            CompressedImage,
            '/edu/camera_frame',
            self.image_callback,
            qos_profile
        )
        
        self.latest_frame_b64 = None
        self.last_frame_time = 0
        self.lock = threading.Lock()
        
        logger.info("CameraBridgeNode запущен, ожидание кадров...")

    def image_callback(self, msg: CompressedImage):
        """
        Получаем JPEG байты, конвертируем в Base64 для отправки через JSON.
        """
        try:
            # msg.data уже содержит байты jpeg (так как CompressedImage)
            # Конвертируем байты в base64 строку
            b64_data = base64.b64encode(msg.data).decode('utf-8')
            
            with self.lock:
                self.latest_frame_b64 = b64_data
                self.last_frame_time = time.time()
                
        except Exception as e:
            logger.error(f"Ошибка обработки кадра: {e}")

    def get_frame(self):
        with self.lock:
            return self.latest_frame_b64


class CameraSession:
    """
    Сессия для отправки видео.
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
                self.running = False # Разрываем соединение при ошибке отправки
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
        last_sent_time = 0
        target_fps = 20 # Ограничим FPS отправки, чтобы не забить канал
        interval = 1.0 / target_fps
        
        while self.is_streaming and self.running:
            now = time.time()
            
            # Простая стабилизация FPS
            if now - last_sent_time < interval:
                time.sleep(0.005)
                continue

            frame = self.ros_node.get_frame()
            if frame:
                # Проверяем, не отправляем ли мы старый кадр (опционально)
                # Но лучше слать, чтобы клиент знал, что связь жива
                
                response = {
                    "command": "stream_frame",
                    "image": frame,
                    "timestamp": now
                }
                
                if not self.send_json(response):
                    break # Ошибка отправки - выход
                
                last_sent_time = now
            else:
                time.sleep(0.1)


def start_server():
    rclpy.init()
    camera_node = CameraBridgeNode()
    
    # ROS spin в отдельном потоке
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
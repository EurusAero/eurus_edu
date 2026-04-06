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

BUFFER_SIZE = 4096

class CameraBridgeNode(Node):
    def __init__(self):
        super().__init__('edu_camera_server')
        
        self.qos_profile = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            depth=1
        )
        
        self.latest_frames_b64 = {}
        self.subs = {}
        
        # Подписка на результаты YOLO (одна общая, либо можете переделать под каждую камеру)
        self.target_sub = self.create_subscription(
            String,
            '/edu/targets',
            self.target_callback,
            10
        )
        
        self.latest_targets = None
        self.lock = threading.Lock()
        
        self.get_logger().info("MultiCameraBridgeNode запущен, ожидание конфигурации...")

    def add_camera(self, camera_name):
        """Динамическое добавление подписки на камеру."""
        topic_name = f'/edu/{camera_name}'
        
        with self.lock:
            self.latest_frames_b64[camera_name] = None
            
        # Используем замыкание (lambda), чтобы передать имя камеры в коллбек
        cb = lambda msg, c_name=camera_name: self.image_callback(msg, c_name)
        
        self.subs[camera_name] = self.create_subscription(
            CompressedImage,
            topic_name,
            cb,
            self.qos_profile
        )
        self.get_logger().info(f"Подписка на топик создана: {topic_name}")

    def image_callback(self, msg: CompressedImage, camera_name: str):
        try:
            b64_data = base64.b64encode(msg.data).decode('utf-8')
            with self.lock:
                self.latest_frames_b64[camera_name] = b64_data
        except Exception as e:
            self.get_logger().warn(f"Ошибка обработки кадра для {camera_name}: {e}")

    def target_callback(self, msg: String):
        try:
            data = json.loads(msg.data)
            with self.lock:
                self.latest_targets = data
        except json.JSONDecodeError:
            self.get_logger().warn(f"Получен битый JSON в /edu/targets: {msg.data}")

    def get_frame(self, camera_name):
        with self.lock:
            return self.latest_frames_b64.get(camera_name)
            
    def get_targets(self):
        with self.lock:
            return self.latest_targets


class CameraSession:
    def __init__(self, conn, addr, ros_node: CameraBridgeNode, camera_name: str, fps: int):
        self.conn = conn
        self.addr = addr
        self.ros_node = ros_node
        self.camera_name = camera_name
        self.fps = fps
        self.sock_utils = SocketsUtils()
        
        self.is_streaming = False
        self.stream_thread = None
        self.socket_lock = threading.Lock()
        self.running = True

    def start(self):
        self.ros_node.get_logger().info(f"[{self.camera_name}] Видео-сессия начата для {self.addr}")
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
            self.ros_node.get_logger().info(f"[{self.camera_name}] Клиент {self.addr} отключился.")
        except Exception as e:
            self.ros_node.get_logger().error(f"[{self.camera_name}] Ошибка сессии {self.addr}: {e}", exc_info=True)
        finally:
            self.stop_stream()
            self.conn.close()
            self.ros_node.get_logger().info(f"[{self.camera_name}] Видео-сессия завершена для {self.addr}")

    def send_json(self, data):
        with self.socket_lock:
            try:
                self.sock_utils.send_json(self.conn, data)
                return True
            except Exception as e:
                self.ros_node.get_logger().error(f"[{self.camera_name}] Ошибка отправки данных: {e}")
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
            self.ros_node.get_logger().error(f"Ошибка при декодировании JSON сообщения во время обработки команды: {e}")
        except Exception as e:
            self.ros_node.get_logger().error(f"Ошибка при обработке команды: {e}")

    def _send_single_frame(self):
        frame = self.ros_node.get_frame(self.camera_name)
        if frame:
            response = {"command": "frame_response", "image": frame, "timestamp": time.time()}
            self.send_json(response)
        else:
            self.send_json({"command": "error", "message": "Нет доступных кадров"})

    def _send_targets(self):
        targets = self.ros_node.get_targets()
        if targets:
            self.send_json(targets)
        else:
            empty_response = {"command": "targets_response", "all_objects": []}
            self.send_json(empty_response)

    def start_stream(self):
        self.is_streaming = True
        self.stream_thread = threading.Thread(target=self._stream_loop, daemon=True)
        self.stream_thread.start()
        self.ros_node.get_logger().info(f"[{self.camera_name}] Поток видео запущен.")

    def stop_stream(self):
        self.is_streaming = False
        if self.stream_thread and self.stream_thread.is_alive():
            self.stream_thread.join(timeout=1.0)
        self.ros_node.get_logger().info(f"[{self.camera_name}] Поток видео остановлен.")

    def _stream_loop(self):
        interval = 1.0 / self.fps
        
        while self.is_streaming and self.running:
            now = time.time()
            frame = self.ros_node.get_frame(self.camera_name)
            if frame:
                response = {"command": "stream_frame", "image": frame, "timestamp": now}
                if not self.send_json(response):
                    break
                
            loop_interval = time.time() - now
            time.sleep(max(0, (interval - loop_interval)))


class SocketServerThread(threading.Thread):
    def __init__(self, ros_node: CameraBridgeNode, camera_name: str, host: str, port: int, fps: int):
        super().__init__(daemon=True)
        self.ros_node = ros_node
        self.camera_name = camera_name
        self.host = host
        self.port = port
        self.fps = fps
        self.server_socket = None
        self.active_session_thread = None

    def run(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen()
            self.ros_node.get_logger().info(f"[{self.camera_name}] Сервер слушает {self.host}:{self.port}")
            
            while True:
                conn, addr = self.server_socket.accept()
                
                # Single Client Check per camera
                if self.active_session_thread is not None and self.active_session_thread.is_alive():
                    self.ros_node.get_logger().warn(f"[{self.camera_name}] Соединение {addr} отклонено (сервер занят).")
                    conn.close()
                    continue
                
                session = CameraSession(conn, addr, self.ros_node, self.camera_name, self.fps)
                self.active_session_thread = threading.Thread(target=session.start, daemon=True)
                self.active_session_thread.start()
                
        except Exception as e:
            self.ros_node.get_logger().error(f"[{self.camera_name}] Ошибка сервера: {e}")
        finally:
            if self.server_socket:
                self.server_socket.close()

def main():
    rclpy.init()
    node = CameraBridgeNode()
    
    config = configparser.ConfigParser()
    home_dir = os.getenv("HOME")
    config_path = f"{home_dir}/ros2_ws/src/eurus_edu/edu_camera_stream/eurus.ini"
    
    server_threads = []
    
    if os.path.exists(config_path):
        config.read(config_path)
        
        for section in config.sections():
            if section.endswith('_server'):
                camera_name = section.replace('_server', '')
                
                if config.has_section(camera_name) and config.getboolean(camera_name, "enable", fallback=False):
                    host = config[section].get('host', '0.0.0.0')
                    port = config[section].getint('port')
                    fps = config[camera_name].getint('fps', 30)
                    
                    node.add_camera(camera_name)
                    
                    srv_thread = SocketServerThread(node, camera_name, host, port, fps)
                    server_threads.append(srv_thread)
                    srv_thread.start()
    else:
        node.get_logger().error(f"Файл конфига не найден: {config_path}")

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info("Остановка серверов...")
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == "__main__":
    main()
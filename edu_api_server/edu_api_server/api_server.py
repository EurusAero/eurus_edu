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

from std_msgs.msg import String, Bool
from edu_msgs.msg import Command

# Перекинуть в Ноду для логирования
config = configparser.ConfigParser()
home_dir = os.getenv("HOME")
config_path = f'{home_dir}/ros2_ws/src/eurus_edu/edu_api_server/eurus.ini'

if os.path.exists(config_path):
    config.read(config_path)
    HOST = config['server'].get('host')
    PORT = int(config['server'].get('port'))
    BUFFER_SIZE = int(config['server'].get('buffer_size'))


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

        # Публикация команд для дрона (отправляем pending)
        self.cmd_pub = self.create_publisher(Command, 'edu/command', qos_profile)
        
        # Публикация команд для LED ленты (JSON String)
        self.led_pub = self.create_publisher(String, 'edu/led_control', qos_profile)
        
        self.aruco_map_pub = self.create_publisher(String, "edu/aruco_map_nav", qos_profile)
        
        self.startgame_pub = self.create_publisher(String, "edu/game_started", qos_profile)
        
        # Публикация и подписка для Лазертага
        self.lasertag_pub = self.create_publisher(String, 'edu/lasertag', qos_profile)
        self.lasertag_sub = self.create_subscription(
            String,
            'edu/lasertag',
            self.lasertag_callback,
            qos_profile
        )

        # Подписка на изменение статуса команд дрона (от контроллера)
        self.status_sub = self.create_subscription(
            Command, 
            'edu/command', 
            self.command_status_callback, 
            qos_profile
        )
        
        # Подписка на телеметрию
        self.telemetry_sub = self.create_subscription(
            String,
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
        self.get_logger().info("API нода создана")

    def set_active_session(self, session):
        with self.session_lock:
            self.active_session = session
        self.get_logger().debug(f"Установленна активная сессия - {session}")

    def remove_active_session(self, session):
        with self.session_lock:
            if self.active_session == session:
                self.active_session = None
        self.get_logger().debug(f"Очищенна активная сессия - {session}")


    def telemetry_callback(self, msg):
        """Обновляем кэш телеметрии из топика."""
        try:
            data = json.loads(msg.data)
            self.latest_telemetry = data
        except json.JSONDecodeError:
            self.get_logger().warn("Получена некорректная JSON телеметрия из ROS топика")

    def lasertag_callback(self, msg):
        """
        Обработка ответов от ноды лазертага.
        Нода присылает JSON с command="shoot" и status="success".
        Мы транслируем это клиенту как action="laser_shot".
        """
        try:
            data = json.loads(msg.data)
            cmd = data.get("command")
            status = data.get("status")
            
            # Мы реагируем только на успешное завершение выстрела
            if cmd == "shoot" and status == COMPLETED_STATUS:
                response_data = {
                    "command": "action_status",
                    "action": "laser_shot", # SDK ждет именно это имя
                    "status": COMPLETED_STATUS,
                    "message": data.get("message", "Shot fired")
                }
                
                with self.session_lock:
                    if self.active_session:
                        self.active_session.send_json(response_data)
                        self.get_logger().info("Подтверждение выстрела отправлено клиенту.")

        except json.JSONDecodeError:
            self.get_logger().warn("Ошибка JSON в lasertag callback")
        except Exception as e:
            self.get_logger().warn(f"Ошибка обработки callback лазертага: {e}")

    def command_status_callback(self, msg: Command):
        """
        Коллбек, когда контроллер обновляет статус команд ДВИЖЕНИЯ.
        """
        if not self.is_busy or abs(msg.timestamp - self.current_command_id) > 0.0001:
            return

        status = msg.status
        
        self.get_logger().info(f"Обновление статуса команды '{msg.command}': {status}")

        response_data = {
            "command": "action_status",
            "action": msg.command,
            "status": status,
            "message": msg.data
        }

        with self.session_lock:
            if self.active_session:
                self.active_session.send_json(response_data)

        if status in [COMPLETED_STATUS, DENIED_STATUS]:
            self.is_busy = False
            self.current_command_name = None
            self.get_logger().info(f"Поток команд разблокирован. Команда '{msg.command}' завершена со статусом {status}.")

    def process_client_command(self, request_msg: dict, session):
        """
        Обработка входящего JSON от клиента.
        """
        cmd_name = request_msg.get("command")
        
        if cmd_name == "led_control":
            try:
                msg = String()
                msg.data = json.dumps(request_msg)
                self.led_pub.publish(msg)
                self.get_logger().info(f"LED команда отправлена в топик: {request_msg.get('effect', 'unknown')}")
            except Exception as e:
                self.get_logger().warn(f"Ошибка публикации LED команды: {e}")
            return None

        elif cmd_name == "start_game":
            try:
                msg = String()
                msg.data = json.dumps(request_msg)
                self.startgame_pub.publish(msg)
                self.get_logger().info(f"Сообщение о статусе игры отправлено в топик")
            except Exception as e:
                self.get_logger().warn(f"Ошибка публикации статуса игры: {e}")
            return None
        
        elif cmd_name == "laser_shot":
            try:
                # Нода лазертага ждет команду "shoot"
                payload = {
                    "command": "shoot",
                    "status": PENDING_STATUS,
                    "timestamp": time.time()
                }
                
                msg = String()
                msg.data = json.dumps(payload)
                self.lasertag_pub.publish(msg)
                
                self.get_logger().info("Команда выстрела отправлена в топик /edu/lasertag")
                
                self.set_active_session(session)
                
                return {
                    "command": "action_status",
                    "action": "laser_shot",
                    "status": PENDING_STATUS,
                    "message": "Shot initiated"
                }
            except Exception as e:
                self.get_logger().warn(f"Ошибка отправки выстрела: {e}")
                return {
                    "command": "action_status",
                    "action": "laser_shot",
                    "status": DENIED_STATUS,
                    "message": str(e)
                }

        elif cmd_name == "request_telemetry":
            # self.get_logger().debug("sending telemetry")
            return {
                "command": "response_telemetry",
                "telemetry": self.latest_telemetry
            }
        elif cmd_name == "point_reached":
            return {
                "command": "point_reached",
                "point_reached": self.latest_telemetry.get("point_reached", False)
            }
        elif cmd_name == "aruco_map_navigation":
            try:
                payload = {
                    "timestamp": time.time(),
                    "aruco_nav_status": request_msg.get("state"),
                    "map_in_vision": False,
                    "fly_in_borders": request_msg.get("fly_in_borders")
                }
                
                msg = String()
                msg.data = json.dumps(payload)
                self.aruco_map_pub.publish(msg)
                                
                return {
                    "command": "action_status",
                    "action": cmd_name,
                    "status": COMPLETED_STATUS,
                    "message": "Request accepted"
                }
            except Exception as e:
                self.get_logger().error(f"Exeptiong getting aruco map navigation {e}")
        elif cmd_name in DRONE_COMMANDS:
            if self.is_busy:
                return {
                    "command": "action_status",
                    "action": cmd_name,
                    "status": DENIED_STATUS,
                    "message": f"Server busy executing: {self.current_command_name}"
                }
            
            try:
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
                self.get_logger().info(f"Опубликована команда в ROS: {cmd_name}, ID: {self.current_command_id}")

                return {
                    "command": "action_status",
                    "action": cmd_name,
                    "status": PENDING_STATUS,
                    "message": "Command sent to controller"
                }
            
            except Exception as e:
                self.get_logger().error(f"Ошибка отправки комманды: {e}")
                return {
                    "command": "action_status",
                    "action": cmd_name,
                    "status": DENIED_STATUS,
                    "message": str(e)
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
        self.get_logger().info(f"Отправленна принудительная команда посадки.")
        self.is_busy = False
    
    def force_aruco_map_disable(self):
        msg = String()
        payload = {
                    "timestamp": time.time(),
                    "aruco_nav_status": False,
                    "map_in_vision": False,
                    "fly_in_borders": False
                }
        msg.data = json.dumps(payload)
        self.aruco_map_pub.publish(msg)
        self.get_logger().info(f"Принудительное завершение навигации по аруко карте")


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
        self.ros_node.get_logger().info(f"Сессия начата для {self.addr}")
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
            self.ros_node.get_logger().info(f"Клиент {self.addr} разорвал соединение.")
        except Exception as e:
            self.ros_node.get_logger().warn(f"Ошибка сессии {self.addr}: {e}", exc_info=True)
        finally:
            self.ros_node.force_land()
            self.ros_node.force_aruco_map_disable()
            self.ros_node.remove_active_session(self)
            self.conn.close()
            self.ros_node.get_logger().info(f"Сессия завершена для {self.addr}")

    def send_json(self, data):
        """Отправка JSON клиенту (потокобезопасно)."""
        with self.socket_lock:
            try:
                self.sock_utils.send_json(self.conn, data)
                # logger.debug(f"Отправлено клиенту {self.addr}: {data.get('command')}")
            except Exception as e:
                self.ros_node.get_logger().warn(f"Не удалось отправить данные {self.addr}: {e}")

    def _handle_request(self, json_data):
        try:
            message = json.loads(json_data)
            self.msg_utils.validate_message(message)
            cmd = message.get("command")

            if cmd in DRONE_COMMANDS:
                self.send_json({
                    "command": "response",
                    "status": "success",
                    "message": "received"
                })

            result = self.ros_node.process_client_command(message, self)
            
            if result:
                self.send_json(result)

        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            self.ros_node.get_logger().warn(f"Ошибка обработки от {self.addr}: {e}")
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

    edu_node.get_logger().info(f"Запуск TCP сервера EurusEdu на {HOST}:{PORT}...")
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    active_client_thread = None

    try:
        server.bind((HOST, PORT))
        server.listen()

        while True:
            conn, addr = server.accept()

            if active_client_thread is not None and active_client_thread.is_alive():
                edu_node.get_logger().warn(f"Входящее соединение от {addr} отклонено: сервер занят другим клиентом.")
                conn.close()
                continue
            
            session = ClientSession(conn, addr, edu_node)
            
            active_client_thread = threading.Thread(target=session.start)
            active_client_thread.daemon = True
            active_client_thread.start()
            
            edu_node.get_logger().info(f"Клиент {addr} принят.")

    except KeyboardInterrupt:
        edu_node.get_logger().info("\nОстановка сервера...")
    except Exception as e:
        edu_node.get_logger().error(f"Критическая ошибка сервера: {e}", exc_info=True)
    finally:
        server.close()
        try:
            edu_node.destroy_node()
            rclpy.shutdown()
        except Exception:
            pass

if __name__ == "__main__":
    start_server()
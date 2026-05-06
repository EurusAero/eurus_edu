import socket
import threading
import json
import time
import logging
from .utils import SocketsUtils
from .const import *


class EurusControl:
    def __init__(self, ip: str, port: int, do_log: bool = True, log_file: str = None, socket_timeout_time: float  = 3, auto_connect: bool = True):
        self.ip = ip
        self.port = port
        self.sock = None
        self.is_connected = False
        self.running = False

        self.do_log = do_log
        
        self.logger = logging.getLogger("EurusEdu")
        self.logger.setLevel(logging.DEBUG)
        self.logger.handlers = []
        
        formatter = logging.Formatter(u'[%(asctime)s] [%(levelname)s] %(message)s')
        
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)
        
        if log_file:
            file_handler = logging.FileHandler(log_file,encoding='utf-8')
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)

        self.sock_utils = SocketsUtils()
        self.listener_thread = None

        self.heartbeat_thread = None
        
        # Локи
        self._socket_lock = threading.Lock()    # Для защиты отправки байтов в сокет
        self._movement_lock = threading.Lock()  # Для блокировки команд движения
        
        # События синхронизации
        self._response_event = threading.Event()
        self._action_started_event = threading.Event()
        self._action_finished_event = threading.Event()
        self._telemetry_event = threading.Event()
        self._point_reached_event = threading.Event()
    
        self._laser_event = threading.Event()
        
        # Данные
        self._last_telemetry_data = {}
        self._last_point_reached_data = {}
        self._last_response_status = None
        
        self._last_action_code = None
        self._last_action_message = ""
        
        self._last_laser_status = None

        self.socket_timeout_time = socket_timeout_time

        self._last_heartbeat = time.time()

        if auto_connect:
            self.connect()

    def connect(self):
        if self.is_connected:
            if self.do_log: self.logger.warning("Уже подключен.")
            return False

        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(self.socket_timeout_time)
            self.sock.connect((self.ip, self.port))
            self.is_connected = True
            self.running = True
            
            self.listener_thread = threading.Thread(target=self._listen_server, daemon=True)
            self.listener_thread.start()
            
            self.heartbeat_thread = threading.Thread(target=self._heartbeat_server, daemon=True)
            self.heartbeat_thread.start()

            if self.do_log:
                self.logger.info(f"Успешное подключение к {self.ip}:{self.port}")

            return True

        except Exception as e:
            if self.do_log: self.logger.error(f"Ошибка подключения: {e}")
            self.is_connected = False

            return False

    def disconnect(self):
        if not self.running: return False
        
        self.running = False
        self.is_connected = False
        
        # Разблокируем любые зависшие ожидания
        self._response_event.set()
        self._action_started_event.set()
        self._action_finished_event.set()
        self._telemetry_event.set()
        self._point_reached_event.set()
        self._laser_event.set()

        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        if self.do_log:
            self.logger.info("Соединение закрыто.")
        return True

    def _heartbeat_server(self):
        while self.running:
            try:
                timestamp = time.time()

                payload = {
                    "command": "heartbeat",
                    "timestamp": time.time()
                }
                self._send_raw(payload)
                
                time.sleep(max(0, 1 - (timestamp - self._last_heartbeat)))
            
                self._last_heartbeat = timestamp

            except Exception as e:
                if self.do_log: self.logger.error("Ошибка в потоке heartbeat")


    def _listen_server(self):
        buffer = b""
        while self.running:
            try:
                try:
                    chunk = self.sock.recv(1024)
                except socket.timeout as e:
                    continue 
                except Exception as e:
                    if self.do_log: self.logger.error(f"Ошибка в listener_server: {e}")
                    break 

                if not chunk:
                    if self.do_log: self.logger.warning("Сервер закрыл соединение.")
                    self.disconnect()
                    break
                
                buffer += chunk
                messages, buffer = self.sock_utils.parse_buffer(buffer)

                for raw_msg in messages:
                    if raw_msg is None: continue
                    try:
                        msg_dict = json.loads(raw_msg)
                        command = msg_dict.get("command")
                        
                        if command == "response":
                            if self.do_log: self.logger.info(f" - Получен ответ: {msg_dict.get('status')}")
                            self._last_response_status = msg_dict.get("status")
                            self._response_event.set()
                            
                        elif command == "action_status":
                            action_name = msg_dict.get("action")
                            code = msg_dict.get("status")
                            message = msg_dict.get("message", "")

                            if action_name == "laser_shot":
                                if self.do_log: self.logger.info(f" - Получен статус от лазера: {code}")
                                
                                if code in [COMPLETED_STATUS, DENIED_STATUS]:
                                    self._last_laser_status = code
                                    self._laser_event.set()
                            else:
                                self._last_action_message = message
                                if self.do_log: self.logger.info(f" - Получен статус: {command} ({action_name}): {code} ({self._last_action_message})")

                                if code == PENDING_STATUS:
                                    self._action_started_event.set()
                                elif code in [COMPLETED_STATUS, DENIED_STATUS]:
                                    self._last_action_code = code
                                    self._action_finished_event.set()
                                    self._action_started_event.set() 
                            
                        elif command == "response_telemetry":
                            self._last_telemetry_data = msg_dict.get("telemetry", {})
                            self._telemetry_event.set()
                        
                        elif command == "point_reached":
                            self._last_point_reached_data = msg_dict.get("point_reached", {})
                            self._point_reached_event.set()
                            
                    except json.JSONDecodeError:
                        if self.do_log: self.logger.error(f"Битый JSON: {raw_msg}")
                        
            except Exception as e:
                if self.do_log: self.logger.error(f"Ошибка в listener: {e}")
                if self.running:
                    self.disconnect()
                break

    def _send_raw(self, payload):
        with self._socket_lock:
            try:
                if self.sock:
                    self.sock_utils.send_json(self.sock, payload)
                    if payload["command"] in DRONE_COMMANDS and self.do_log:
                        self.logger.info(f" - Отправлена комманда: {payload['command']}")
            except Exception as e:
                if self.do_log: self.logger.error(f"Ошибка отправки: {e}")
                self.disconnect()

    def _smart_wait(self, event: threading.Event, timeout: float = None, error_msg: str = None) -> bool:
        start_time = time.time()
        step = 0.5

        while not event.is_set():
            if not self.running:
                return False
            
            if timeout and (time.time() - start_time > timeout):
                if error_msg:
                    if self.do_log: self.logger.error(error_msg)
                return False

            try:
                event.wait(timeout=step)
            except KeyboardInterrupt:
                self.disconnect()
                raise

        return True

    def _send_movement_command(self, payload):
        if not self.is_connected:
            if self.do_log: self.logger.error("Нет соединения.")
            return False

        try:
            with self._movement_lock:
                self._response_event.clear()
                self._action_started_event.clear()
                self._action_finished_event.clear()

                cmd_name = payload['command']
                self._send_raw(payload)

                if not self._smart_wait(self._response_event, 30.0, "ТАЙМ-АУТ: Нет ответа от сервера!"):
                    return False

                if self._last_response_status != "success":
                    if self.do_log: self.logger.error("Сервер вернул ошибку в response.")
                    return False
                
                if not self._smart_wait(self._action_started_event, 10.0, f"Команда {cmd_name} не перешла в PENDING"):
                    return False

                if self._action_finished_event.is_set() and self._last_action_code == DENIED_STATUS:
                    if self.do_log: self.logger.error(f"Команда {cmd_name} отклонена: {self._last_action_message}")
                    return False

                if not self._smart_wait(self._action_finished_event, timeout=None):
                    if self.do_log: self.logger.warning("Ожидание завершения прервано (отключение).")
                    return  False
                
                if self._last_action_code == COMPLETED_STATUS:
                    if self.do_log: self.logger.info(f"Команда {cmd_name} успешно завершена.")
                else:
                    if self.do_log: self.logger.error(f"Команда {cmd_name} провалена (Status: {self._last_action_code}). Msg: {self._last_action_message}")
                    self.disconnect()
                return False

        except KeyboardInterrupt:
            self.disconnect()
            raise

    def set_mode(self, mode):
        return self._send_movement_command({"command": "set_mode", "mode": mode})

    def arm(self):
        return self._send_movement_command({"command": "arm"})

    def disarm(self):
        return self._send_movement_command({"command": "disarm"})

    def takeoff(self, altitude, speed=1):
        return self._send_movement_command({"command": "takeoff", "altitude": float(altitude), "speed": float(speed)})

    def land(self):
        return self._send_movement_command({"command": "land"})
    
    def move_to_local_point(self, x = None, y = None, z = None, speed=1, yaw=None):
        return self._send_movement_command({
            "command": "move_to_local_point",
            "x": float(x) if x is not None else float("-inf"), 
            "y": float(y) if y is not None else float("-inf"), 
            "z": float(z) if z is not None else float("-inf"),
            "yaw": float(yaw) if yaw is not None else None,
            "speed": float(speed)
        })
    
    def move_in_body_frame(self, x = None, y = None, z = None, speed=1, yaw=None):
        return self._send_movement_command({
            "command": "move_in_body_frame", 
            "x": float(x) if x is not None else 0, 
            "y": float(y) if y is not None else 0, 
            "z": float(z) if z is not None else 0,
            "yaw": float(yaw) if yaw is not None else None,
            "speed": float(speed)
        })
    
    def set_velocity(self, vx = 0, vy = 0, vz = 0, yaw_rate=None):
        return self._send_movement_command({
            "command": "set_velocity",
            "vx": float(vx),
            "vy": float(vy),
            "vz": float(vz),
            "yaw_rate": float(yaw_rate) if yaw_rate is not None else None
        })

    def get_telemetry(self):
        if not self.is_connected: return None
        
        self._telemetry_event.clear()
        self._response_event.clear()

        self._send_raw({"command": "request_telemetry"})

        if self._smart_wait(self._telemetry_event, timeout=2.0):
            return self._last_telemetry_data
        else:
            return None
    
    def point_reached(self):
        if not self.is_connected: return False
        
        self._point_reached_event.clear()
        self._response_event.clear()
        
        self._send_raw({"command": "point_reached"})
        
        if self._smart_wait(self._point_reached_event, timeout=2.0):
            return self._last_point_reached_data
        else:
            return False

    def led_control(self, effect: str, r: int = 0, g: int = 0, b: int = 0, nLED: int = 50, brightness: float = 1.0, speed: float | None = None):
        if not self.is_connected:
            if self.do_log: self.logger.error("Нет соединения для отправки команды LED.")
            return False

        payload = {
            "command": "led_control",
            "effect": str(effect),
            "nLED": int(nLED),
            "brightness": float(brightness),
            "color": [int(r), int(g), int(b)],
            "speed": speed
        }
        
        self._send_raw(payload)

    def laser_shot(self):
        if not self.is_connected:
            return False

        self._laser_event.clear()
        self._last_laser_status = None

        payload = {"command": "laser_shot"}
        
        self._send_raw(payload)

        if self._smart_wait(self._laser_event, timeout=2.0):
            if self._last_laser_status == COMPLETED_STATUS:
                if self.do_log: self.logger.info("Выстрел лазером успешен.")
                return True
            else:
                if self.do_log: self.logger.warning(f"Выстрел лазером не удался/отменён: {self._last_laser_status}")
                return False
        else:
            if self.do_log: self.logger.error("Превышено время ожидания для выстрела лазером (нет подтверждения от сервера).")
            return False
    
    def aruco_map_navigation(self, state=False, fly_in_borders=True):
        if not self.is_connected:
            if self.do_log: self.logger.warning("Нет соединения для отправки команды.")
            return False
        
        payload = {"command": "aruco_map_navigation", "state": state, "fly_in_borders": fly_in_borders}
        
        self._send_raw(payload)
    
    def move_to_marker(self, marker_id: str | int, z: float, speed: float = 1.0, yaw: float = None):
        if not self.is_connected:
            if self.do_log: self.logger.warning("Нет соединения для отправки команды.")
            return False
        
        payload = {
            "command": "move_to_marker",
            "marker_id": str(marker_id),
            "z": float(z),
            "yaw": float(yaw) if yaw is not None else None,
            "speed": float(speed)
        }
        
        self._send_movement_command(payload)
    
    def start_game(self, start_game: bool = False, team_color: str | list = "red"):
        if not self.is_connected:
            if self.do_log: self.logger.error("Нет соединения для отправки команды LED.")
            return False

        payload = {
            "command": "start_game",
            "start_game": start_game,
            "team_color": team_color
            }
        
        self._send_raw(payload)
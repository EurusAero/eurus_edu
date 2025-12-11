import socket
import threading
import json
import time
import logging
import sys
from .utils import SocketsUtils
from .const import *



class EurusControl:
    def __init__(self, ip: str, port: int, console_log: bool = True, log_file: str = None):
        self.ip = ip
        self.port = port
        self.sock = None
        self.is_connected = False
        self.running = False
        self.console_log = console_log
        
        self.logger = logging.getLogger("EurusEdu")
        self.logger.setLevel(logging.DEBUG)
        self.logger.handlers = []
        
        formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s')
        
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)
        
        if log_file:
            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)

        self.sock_utils = SocketsUtils()
        self.listener_thread = None
        
        self._socket_lock = threading.Lock()
        self._movement_lock = threading.Lock()
        
        self._response_event = threading.Event()
        self._action_started_event = threading.Event()
        self._action_finished_event = threading.Event()
        self._telemetry_event = threading.Event()
        self._point_reached_event = threading.Event()
        
        self._last_telemetry_data = {}
        self._last_response_status = None
        self._last_action_code = None
        self._last_action_message = ""

    def connect(self):
        if self.is_connected:
            self.logger.warning("Уже подключен.")
            return

        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(1.0)
            self.sock.connect((self.ip, self.port))
            self.is_connected = True
            self.running = True
            
            self.listener_thread = threading.Thread(target=self._listen_server, daemon=True)
            self.listener_thread.start()
            
            self.logger.info(f"Успешное подключение к {self.ip}:{self.port}")
            
        except Exception as e:
            self.logger.error(f"Ошибка подключения: {e}")
            self.is_connected = False

    def disconnect(self):
        if not self.running: return # Уже отключены
        
        self.running = False
        self.is_connected = False
        
        # Разблокируем любые зависшие ожидания
        self._response_event.set()
        self._action_started_event.set()
        self._action_finished_event.set()
        self._telemetry_event.set()
        self._point_reached_event.set()

        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        self.logger.info("Соединение закрыто.")

    def _listen_server(self):
        """Фоновый поток прослушивания."""
        buffer = b""
        while self.running:
            try:
                # Благодаря self.sock.settimeout(1.0), этот вызов будет
                # выбрасывать socket.timeout каждую секунду, если данных нет.
                # Это позволяет циклу проверить while self.running.
                try:
                    chunk = self.sock.recv(1024)
                except socket.timeout:
                    continue # Просто проверяем self.running и слушаем дальше
                except OSError:
                    break # Сокет закрыт

                if not chunk:
                    self.logger.warning("Сервер закрыл соединение.")
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
                            if self.console_log:
                                self.logger.info(f"[RX] ACK: {msg_dict.get('status')}")
                            self._last_response_status = msg_dict.get("status")
                            self._response_event.set()
                            
                        elif command == "action_status":
                            code = msg_dict.get("status")
                            self._last_action_message = msg_dict.get("message", "")
                            if self.console_log:
                                self.logger.info(f"[RX] {command}: {code} ({self._last_action_message})")

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
                        self.logger.error(f"Битый JSON: {raw_msg}")
                        
            except Exception as e:
                self.logger.error(f"Ошибка в listener: {e}")
                if self.running:
                    self.disconnect()
                break

    def _send_raw(self, payload):
        with self._socket_lock:
            try:
                if self.sock:
                    self.sock_utils.send_json(self.sock, payload)
                    if payload["command"] in DRONE_COMMANDS and self.console_log:
                        self.logger.info(f"[TX] {payload['command']}")
            except Exception as e:
                self.logger.error(f"Ошибка отправки: {e}")
                self.disconnect()

    def _smart_wait(self, event: threading.Event, timeout: float = None, error_msg: str = None) -> bool:
        start_time = time.time()
        step = 0.5

        while not event.is_set():
            if not self.running:
                return False
            
            if timeout and (time.time() - start_time > timeout):
                if error_msg:
                    self.logger.critical(error_msg)
                return False

            try:
                event.wait(timeout=step)
            except KeyboardInterrupt:
                self.disconnect()
                raise

        return True

    def _send_movement_command(self, payload):
        if not self.is_connected:
            self.logger.error("Нет соединения.")
            return

        try:
            with self._movement_lock:
                self._response_event.clear()
                self._action_started_event.clear()
                self._action_finished_event.clear()

                cmd_name = payload['command']
                self._send_raw(payload)

                # 1. Ждем ACK (30 сек)
                if not self._smart_wait(self._response_event, 30.0, "ТАЙМ-АУТ: Нет ACK от сервера!"):
                    return

                if self._last_response_status != "success":
                    self.logger.error("Сервер вернул ошибку в response.")
                    return
                
                if not self._smart_wait(self._action_started_event, 10.0, f"Команда {cmd_name} не перешла в PENDING"):
                    return

                if self._action_finished_event.is_set() and self._last_action_code == DENIED_STATUS:
                     self.logger.error(f"Команда {cmd_name} отклонена: {self._last_action_message}")
                     return


                if not self._smart_wait(self._action_finished_event, timeout=None):
                    self.logger.warning("Ожидание завершения прервано (дисконнект).")
                    return
                
                if self._last_action_code == COMPLETED_STATUS:
                    self.logger.info(f"Команда {cmd_name} успешно завершена.")
                else:
                    self.logger.error(f"Команда {cmd_name} провалена (Status: {self._last_action_code}). Msg: {self._last_action_message}")
                    self.disconnect()

        except KeyboardInterrupt:
            self.disconnect()
            raise # Обязательно пробрасываем выше

    def set_mode(self, mode):
        self._send_movement_command({"command": "set_mode", "mode": mode})

    def arm(self):
        self._send_movement_command({"command": "arm"})

    def disarm(self):
        self._send_movement_command({"command": "disarm"})

    def takeoff(self, altitude):
        self._send_movement_command({"command": "takeoff", "altitude": float(altitude)})

    def land(self):
        self._send_movement_command({"command": "land"})

    def move_to_local_point(self, x, y, z, yaw=None):
        self._send_movement_command({
            "command": "move_to_local_point", "x": float(x), "y": float(y), "z": float(z),
            "yaw": float(yaw) if yaw is not None else None
        })
    
    def move_in_body_frame(self, x, y, z, yaw=None):
        self._send_movement_command({
            "command": "move_in_body_frame", "x": float(x), "y": float(y), "z": float(z),
            "yaw": float(yaw) if yaw is not None else None
        })
    
    def set_velocity(self, vx, vy, vz, yaw_rate=None):
        self._send_movement_command({
            "command": "set_velocity",
            "vx": float(vx),
            "vy": float(vy),
            "vz": float(vz),
            "yaw_rate": float(yaw_rate) if yaw_rate is not None else None
        })

    def request_telemetry(self):
        if not self.is_connected: return None
        
        self._telemetry_event.clear()
        self._response_event.clear()

        self._send_raw({"command": "request_telemetry"})

        if self._smart_wait(self._telemetry_event, timeout=2.0):
            return self._last_telemetry_data
        else:
            # self.logger.warning("Телеметрия не пришла.") # Можно убрать спам логов
            return None
    
    def point_reached(self):
        if not self.is_connected: return None
        
        self._point_reached_event.clear()
        self._response_event.clear()
        
        self._send_raw({"command": "point_reached"})
        
        if self._smart_wait(self._point_reached_event, timeout=2.0):
            return self._last_point_reached_data
        else:
            return None
    
    def led_control(self, effect: str, r: int = 0, g: int = 0, b: int = 0, nLED: int = 15, brightness: float = 1.0):
        """
        Управление LED лентой без ожидания ответа (Fire-and-forget).
        
        :param effect: Тип эффекта ('static', 'blink', 'rainbow', 'komet', 'clear', 'base')
        :param r: Красный (0-255)
        :param g: Зеленый (0-255)
        :param b: Синий (0-255)
        :param nLED: Количество светодиодов (по умолчанию 15)
        :param brightness: Яркость (0.0 - 1.0)
        """
        if not self.is_connected:
            self.logger.error("Нет соединения для отправки команды LED.")
            return

        payload = {
            "command": "led_control",
            "effect": str(effect),
            "nLED": int(nLED),
            "brightness": float(brightness),
            "color": [int(r), int(g), int(b)]
        }
        
        # Используем _send_raw напрямую, минуя блокировки _movement_lock 
        # и ожидания событий (Event wait).
        self._send_raw(payload)
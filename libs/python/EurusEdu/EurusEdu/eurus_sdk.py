import socket
import threading
import json
import time
import logging
import sys
from .utils import SocketsUtils
from .const import *

class EurusControl:
    def __init__(self, ip: str, port: int, log_file: str = None):
        self.ip = ip
        self.port = port
        self.sock = None
        self.is_connected = False
        self.running = False
        
        # --- Настройка Логгера ---
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
        
        # --- Синхронизация ---
        self._socket_lock = threading.Lock()   # Защита отправки данных
        self._movement_lock = threading.Lock() # Защита логики полета (одна команда за раз)
        
        # События
        self._response_event = threading.Event()        # Пришел ACK (response)
        self._action_started_event = threading.Event()  # Пришел код 100 (In Progress)
        self._action_finished_event = threading.Event() # Пришел код 200 или 400
        self._telemetry_event = threading.Event()       # Пришла телеметрия
        
        # Хранилище данных
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
        self.running = False
        self.is_connected = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        self.logger.info("Соединение закрыто.")

    def _listen_server(self):
        """Фоновый поток прослушивания."""
        buffer = b""
        while self.running and self.sock:
            try:
                chunk = self.sock.recv(1024)
                if not chunk:
                    self.logger.warning("Сервер закрыл соединение.")
                    self.disconnect()
                    break
                
                buffer += chunk
                messages, buffer = self.sock_utils.parse_buffer(buffer)
                
                for raw_msg in messages:
                    if raw_msg is None:
                        continue
                        
                    try:
                        msg_dict = json.loads(raw_msg)
                        self.logger.info(f"[RX] {json.dumps(msg_dict, ensure_ascii=False)}")
                        
                        command = msg_dict.get("command")
                        
                        # 1. ACK (подтверждение приема команды)
                        if command == "response":
                            self._last_response_status = msg_dict.get("status")
                            self._response_event.set()
                            
                        # 2. Action Complete (статусы выполнения)
                        elif command == "action_complete":
                            code = msg_dict.get("code")
                            self._last_action_message = msg_dict.get("message", "")
                            
                            if code == CODE_IN_PROGRESS:
                                self._action_started_event.set()
                            elif code in [CODE_SUCCESS, CODE_DENIED]:
                                self._last_action_code = code
                                self._action_finished_event.set()
                            
                        # 3. Телеметрия
                        elif command == "response_telemetry":
                            self._last_telemetry_data = msg_dict.get("telemetry", {})
                            self._telemetry_event.set()
                            
                    except json.JSONDecodeError:
                        self.logger.error(f"Битый JSON: {raw_msg}")
                        
            except socket.error:
                if self.running:
                    self.disconnect()
                break

    def _send_raw(self, payload):
        """Простая отправка без ожиданий (внутренний метод)."""
        with self._socket_lock:
            try:
                self.sock_utils.send_json(self.sock, payload)
                self.logger.info(f"[TX] {payload['command']}")
            except Exception as e:
                self.logger.error(f"Ошибка отправки: {e}")
                self.disconnect()

    def _wait_for_ack(self, timeout=30.0):
        """Ждет подтверждения приема команды (response)."""
        if not self._response_event.wait(timeout=timeout):
            self.logger.critical("ТАЙМ-АУТ: Нет подтверждения (ACK) от сервера 30 сек!")
            return False
        if self._last_response_status != "success":
            self.logger.error("Сервер вернул ошибку в response.")
            return False
        return True

    def _send_movement_command(self, payload):
        """
        Логика для блокирующих команд (goto, takeoff, land).
        1. Отправка -> Ждем ACK (30с).
        2. Ждем CODE 100 (10с). Если нет -> LAND -> Disconnect.
        3. Ждем CODE 200/400 (бесконечно или долго).
        """
        if not self.is_connected:
            self.logger.error("Нет соединения.")
            return

        # Блокируем выполнение других команд движения
        with self._movement_lock:
            # Сброс событий
            self._response_event.clear()
            self._action_started_event.clear()
            self._action_finished_event.clear()

            # 1. Отправка
            self._send_raw(payload)

            # 2. Ожидание ACK (30 сек)
            if not self._wait_for_ack(30.0):
                self.disconnect()
                return

            # 3. Ожидание статуса "В ПРОЦЕССЕ" (10 сек)
            self.logger.info(f"Ожидание начала выполнения {payload['command']}...")
            if not self._action_started_event.wait(timeout=10.0):
                self.logger.critical(f"Команда {payload['command']} не перешла в статус выполнения за 10 cек")
                self.logger.critical("Инициирую аварийную посадку (LAND)...")
                
                #Аварийная отправка LAND (без блокировок, напрямую)
                self._send_raw({"command": "land"})
                
                self.logger.critical("Отключаюсь от сервера.")
                self.disconnect()
                return

            self.logger.info(f"Действие {payload['command']} выполняется (Code {CODE_IN_PROGRESS})...")

            # 4. Ожидание ЗАВЕРШЕНИЯ (Code 200 или 400)
            # Здесь можно поставить wait без таймаута, так как дрон может лететь долго
            self._action_finished_event.wait()
            
            if self._last_action_code == CODE_SUCCESS:
                self.logger.info(f"Действие {payload['command']} успешно завершено (Code 200).")
            else:
                self.logger.error(f"Действие {payload['command']} отклонено/провалено (Code {self._last_action_code}). Msg: {self._last_action_message}")

    def _send_simple_command(self, payload):
        """Для команд типа arm/disarm (ждем только ACK)."""
        if not self.is_connected: return
        
        self._response_event.clear()
        self._send_raw(payload)
        
        if not self._wait_for_ack(30.0):
            self.disconnect()

    # --- API МЕТОДЫ ---

    def arm(self):
        self._send_simple_command({"command": "arm"})

    def disarm(self):
        self._send_simple_command({"command": "disarm"})

    def takeoff(self, altitude):
        self._send_movement_command({
            "command": "takeoff",
            "altitude": float(altitude)
        })

    def land(self):
        self._send_movement_command({"command": "land"})

    def goto(self, x, y, z, yaw):
        self._send_movement_command({
            "command": "goto",
            "x": float(x),
            "y": float(y),
            "z": float(z),
            "yaw": float(yaw)
        })

    def request_telemetry(self):
        """Запрос телеметрии (не блокирует движение)."""
        if not self.is_connected: return None

        self._telemetry_event.clear()
        self._response_event.clear() # Ждем ACK на запрос

        # Отправляем запрос
        self._send_raw({"command": "request_telemetry"})

        # Ждем ACK
        if not self._wait_for_ack(30.0):
            return None

        # Ждем данные
        if self._telemetry_event.wait(timeout=2.0):
            return self._last_telemetry_data
        else:
            self.logger.warning("Телеметрия не пришла.")
            return None
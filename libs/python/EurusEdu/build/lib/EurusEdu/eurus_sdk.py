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
        self._action_started_event = threading.Event()  # Пришел код PENDING (Server принял в работу)
        self._action_finished_event = threading.Event() # Пришел код SUCCESS или DENIED
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
                        
                        # 1. ACK (подтверждение приема JSON)
                        if command == "response":
                            self._last_response_status = msg_dict.get("status")
                            self._response_event.set()
                            
                        # 2. Action Status (статусы выполнения логики)
                        elif command == "action_status":
                            code = msg_dict.get("status")
                            self._last_action_message = msg_dict.get("message", "")
                            
                            if code == PENDING_STATUS:
                                # Сервер сказал "Принял в обработку"
                                self._action_started_event.set()
                                
                            elif code in [COMPLETED_STATUS, DENIED_STATUS]:
                                self._last_action_code = code
                                self._action_finished_event.set()
                                
                                self._action_started_event.set()
                            
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
        """Ждет подтверждения, что сервер валидировал JSON."""
        if not self._response_event.wait(timeout=timeout):
            self.logger.critical("ТАЙМ-АУТ: Нет подтверждения (ACK) от сервера 30 сек!")
            return False
        if self._last_response_status != "success":
            self.logger.error("Сервер вернул ошибку в response.")
            return False
        return True

    def _send_movement_command(self, payload):
        """
        Блокирующий метод отправки команд.
        Ждет пока команда не завершится (success) или не будет отклонена (denied).
        """
        if not self.is_connected:
            self.logger.error("Нет соединения.")
            return

        # Блокируем выполнение других команд движения (Movement Lock)
        # Следующий вызов этого метода встанет здесь в очередь
        with self._movement_lock:
            # Сброс событий
            self._response_event.clear()
            self._action_started_event.clear()
            self._action_finished_event.clear()

            cmd_name = payload['command']

            # 1. Отправка JSON
            self._send_raw(payload)

            # 2. Ожидание ACK (что JSON дошел и валиден)
            if not self._wait_for_ack(30.0):
                self.disconnect()
                return

            # 3. Ожидание статуса PENDING (или быстрого отказа)
            self.logger.info(f"Ожидание запуска команды {cmd_name}...")
            if not self._action_started_event.wait(timeout=10.0):
                self.logger.critical(f"Команда {cmd_name} не перешла в статус обработки (PENDING) за 10 cек")
                self.logger.critical("Возможно сервер занят или завис. Отключаюсь.")
                self.disconnect()
                return

            # Если мы здесь, значит команда либо "pending", либо уже быстро завершилась/отклонилась
            # Проверяем, не отказал ли сервер сразу (busy)
            if self._action_finished_event.is_set() and self._last_action_code == DENIED_STATUS:
                 self.logger.error(f"Команда {cmd_name} отклонена сервером: {self._last_action_message}")
                 return # Выходим, освобождая movement_lock

            self.logger.info(f"Команда {cmd_name} выполняется...")

            self._action_finished_event.wait()
            
            if self._last_action_code == COMPLETED_STATUS:
                self.logger.info(f"Команда {cmd_name} успешно завершена (Status: {COMPLETED_STATUS}).")
            else:
                self.logger.error(f"Команда {cmd_name} завершилась неудачей (Status: {self._last_action_code}). Msg: {self._last_action_message}")
                self.disconnect()
                return

        

    def arm(self):
        # Используем movement_command, чтобы ждать завершения арминга
        self._send_movement_command({"command": "arm"})

    def disarm(self):
        # Используем movement_command, чтобы ждать завершения дизарминга
        self._send_movement_command({"command": "disarm"})

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

        # Телеметрия имеет свою логику ожиданий и не использует movement_lock,
        # поэтому её можно вызывать параллельно полету.
        
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
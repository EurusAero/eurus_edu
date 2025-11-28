import socket
import threading
import json
import time
import logging
from .utils import SocketsUtils
from .const import START_MARKER, END_MARKER


class EurusEdu:
    def __init__(self, ip: str, port: int, log_file: str = None):
        self.ip = ip
        self.port = port
        self.sock = None
        self.is_connected = False
        self.running = False
        
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

        self.sock_utils = SocketsUtils(START_MARKER, END_MARKER)
        
        self.listener_thread = None
        
        # Лок для записи в сокет (чтобы байты разных команд не перемешались)
        self._socket_lock = threading.Lock()
        
        # Лок для блокирующих команд движения (goto, takeoff, land)
        self._movement_lock = threading.Lock()
        
        # События
        self._response_event = threading.Event()       # Пришел любой ответ (ack)
        self._action_complete_event = threading.Event() # Пришло action_complete
        self._telemetry_event = threading.Event()       # Пришла телеметрия
        
        # Хранилище данных
        self._last_telemetry_data = {}
        self._last_response_status = None # success/error

    def connect(self):
        """Подключение к серверу."""
        if self.is_connected:
            self.logger.warning("Дрон уже подключен.")
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
        """Отключение от сервера."""
        self.running = False
        self.is_connected = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        self.logger.info("Отключено от сервера.")

    def _listen_server(self):
        """
        Фоновый поток: слушает сокет, логирует входящие сообщения и управляет событиями.
        """
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
                        # Логируем все входящие сообщения
                        self.logger.info(f"[RX] {json.dumps(msg_dict, ensure_ascii=False)}")
                        
                        command = msg_dict.get("command")
                        
                        # 1. Обработка стандартного ответа (ACK)
                        if command == "response":
                            self._last_response_status = msg_dict.get("status")
                            self._response_event.set()
                            
                        # 2. Обработка завершения действия
                        elif command == "action_complete":
                            self._action_complete_event.set()
                            
                        # 3. Обработка телеметрии
                        elif command == "response_telemetry":
                            self._last_telemetry_data = msg_dict.get("telemetry", {})
                            self._telemetry_event.set()
                            
                    except json.JSONDecodeError:
                        self.logger.error(f"Битый JSON: {raw_msg}")
                        
            except socket.error as e:
                if self.running:
                    self.logger.error(f"Ошибка сокета: {e}")
                    self.disconnect()
                break

    def _send_command(self, payload, wait_for_action=False):
        """
        Универсальный метод отправки.
        1. Отправляет команду.
        2. Ждет подтверждения (response) 30 секунд.
        3. Если wait_for_action=True, ждет action_complete (без таймаута или с большим).
        """
        if not self.is_connected:
            self.logger.error("Нет соединения. Команда отклонена.")
            return

        # Сбрасываем события перед отправкой
        self._response_event.clear()
        if wait_for_action:
            self._action_complete_event.clear()

        # Отправка данных (защищена локом сокета)
        with self._socket_lock:
            try:
                self.sock_utils.send_json(self.sock, payload)
                self.logger.info(f"[TX] Команда отправлена: {payload['command']}")
            except Exception as e:
                self.logger.error(f"Ошибка отправки данных: {e}")
                self.disconnect()
                return

        # --- ОЖИДАНИЕ ПОДТВЕРЖДЕНИЯ (30 сек) ---
        if not self._response_event.wait(timeout=30.0):
            self.logger.critical("ТАЙМ-АУТ: Нет подтверждения от сервера 30 секунд! Отключаемся.")
            self.disconnect()
            return

        # Проверяем статус ответа
        if self._last_response_status != "success":
            self.logger.error(f"Сервер вернул ошибку на команду {payload['command']}.")
            return # Не ждем action_complete, если команда отвергнута

        # --- ОЖИДАНИЕ ЗАВЕРШЕНИЯ ДЕЙСТВИЯ (если нужно) ---
        if wait_for_action:
            self.logger.info(f"Ожидание завершения действия {payload['command']}...")
            self._action_complete_event.wait()
            self.logger.info(f"Действие {payload['command']} завершено.")


    def arm(self):
        """Арминг дрона. Ждет подтверждения приема команды."""
        # Обычно arm не блокирует надолго, но если нужно ждать action_complete,
        # поменяйте wait_for_action=True. По умолчанию ждем только ACK.
        self._send_command({"command": "arm"}, wait_for_action=True)

    def disarm(self):
        """Дизарминг дрона. Ждет подтверждения приема команды."""
        self._send_command({"command": "disarm"}, wait_for_action=False)

    def takeoff(self, altitude):
        """Взлет. Блокирует поток до action_complete."""
        with self._movement_lock:
            self._send_command({
                "command": "takeoff",
                "altitude": float(altitude)
            }, wait_for_action=True)

    def land(self):
        """Посадка. Блокирует поток до action_complete."""
        with self._movement_lock:
            self._send_command({
                "command": "land"
            }, wait_for_action=True)

    def goto(self, x, y, z, yaw):
        """Полет в точку. Блокирует поток до action_complete."""
        with self._movement_lock:
            self._send_command({
                "command": "goto",
                "x": float(x),
                "y": float(y),
                "z": float(z),
                "yaw": float(yaw)
            }, wait_for_action=True)

    def request_telemetry(self):
        """
        Запрос телеметрии.
        Не блокирует movement_lock (можно вызывать во время полета).
        Ждет подтверждения (30с) и затем данных телеметрии.
        """
        if not self.is_connected:
            return None

        self._telemetry_event.clear()
        self._response_event.clear() # Также ждем ACK на сам запрос

        # Отправляем запрос
        with self._socket_lock:
            try:
                self.sock_utils.send_json(self.sock, {"command": "request_telemetry"})
            except Exception:
                return None

        # 1. Ждем ACK (30 сек)
        if not self._response_event.wait(timeout=30.0):
            self.logger.critical("ТАЙМ-АУТ: Нет подтверждения запроса телеметрии! Отключаемся.")
            self.disconnect()
            return None
            
        if self._last_response_status != "success":
            self.logger.error("Сервер отклонил запрос телеметрии.")
            return None

        # 2. Ждем сами данные (таймаут 2 сек, чтобы не висеть вечно)
        if self._telemetry_event.wait(timeout=2.0):
            return self._last_telemetry_data
        else:
            self.logger.warning("Данные телеметрии не пришли вовремя.")
            return None
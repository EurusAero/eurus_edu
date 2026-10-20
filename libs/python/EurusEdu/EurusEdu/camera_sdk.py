import socket
import threading
import json
import time
import logging
import base64
import numpy as np
import cv2

from .utils import SocketsUtils
from .transport import open_socket
from .const import *

class EurusCamera:
    def __init__(self, ip: str, port: int = 8001, log_file: str = None, *,
                 wss_cookie: str | None = None, wss_headers: dict | None = None,
                 wss_origin: str | None = None, wss_ca_file: str | None = None,
                 wss_auth_timeout: float = 120):
        self.ip = ip
        self.port = port
        self._wss_options = dict(wss_cookie=wss_cookie, wss_headers=wss_headers,
                                 wss_origin=wss_origin, wss_ca_file=wss_ca_file,
                                 wss_auth_timeout=wss_auth_timeout)
        self.sock = None
        self.is_connected = False
        self.running = False
        self.is_reconnecting = False
        self._stop_event = threading.Event()
        self._stream_requested = False
        
        self.logger = logging.getLogger("EurusCamera")
        self.logger.setLevel(logging.INFO)
        self.logger.handlers = []
        
        formatter = logging.Formatter('[CAM] [%(asctime)s] [%(levelname)s] %(message)s')
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)
        
        if log_file:
            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)

        self.sock_utils = SocketsUtils()
        self.listener_thread = None
        self._socket_lock = threading.RLock()
        
        self._frame_lock = threading.Lock()
        self._current_frame = None 
        self._last_frame_ts = 0
        
        self._targets_lock = threading.Lock()
        self._latest_targets = None
        self._targets_event = threading.Event()
        
        self._last_target_request_ts = 0 
        
    def connect(self):
        if self.is_connected or self.running:
            self.logger.warning("Уже подключен.")
            return

        try:
            self._stop_event.clear()
            self.sock = open_socket(self.ip, self.port, 2.0, **self._wss_options)
            self.is_connected = True
            self.running = True
            
            self.listener_thread = threading.Thread(target=self._listen_camera, daemon=True)
            self.listener_thread.start()
            
            self.logger.info("Подключено к камере через WSS" if self.ip.startswith('wss://')
                             else f"Подключено к камере {self.ip}:{self.port}")
            
        except Exception as e:
            self.logger.error(f"Ошибка подключения к камере: {e}")
            self.is_connected = False

    def disconnect(self):
        self._stop_event.set()
        with self._socket_lock:
            self._stream_requested = False
            self.running = False
            self.is_connected = False
            self._targets_event.set()
            if self.sock:
                try:
                    self.sock.close()
                except Exception:
                    pass
        self.logger.info("Соединение с камерой закрыто.")

    def _recover(self):
        if not self.running or not self.ip.startswith('wss://') or self._stop_event.is_set():
            return False
        self.is_connected = False
        self.is_reconnecting = True
        self.sock.close()
        with self._frame_lock:
            self._current_frame = None
        with self._targets_lock:
            self._latest_targets = None
        options = dict(self._wss_options, wss_auth_timeout=0)
        deadline = time.monotonic() + 30
        delay = .5
        try:
            while time.monotonic() < deadline and not self._stop_event.wait(delay):
                fresh = None
                try:
                    fresh = open_socket(self.ip, self.port, 2.0, **options)
                    with self._socket_lock:
                        if self._stop_event.is_set():
                            fresh.close()
                            return False
                        self.sock = fresh
                        if self._stream_requested:
                            self.sock_utils.send_json(fresh, {"command": "get_stream"})
                        self.is_connected = True
                    self.logger.info("WSS камеры восстановлен; подписка на поток возобновлена.")
                    return True
                except Exception as error:
                    if fresh:
                        fresh.close()
                    # Revocation must never be bypassed by another browser approval.
                    if isinstance(error, ConnectionError) and 'HTTP 403' in str(error):
                        self.logger.warning("Доступ к камере отклонён. Подключитесь заново для авторизации.")
                        break
                    delay = min(3, delay * 2)
            return False
        finally:
            self.is_reconnecting = False

    def _listen_camera(self):
        buffer = b""
        while self.running:
            try:
                try:
                    chunk = self.sock.recv(4096 * 4)
                except socket.timeout:
                    continue
                except OSError:
                    if self._recover():
                        buffer = b""
                        continue
                    self.disconnect()
                    break

                if not chunk:
                    if self._stop_event.is_set():
                        break
                    code = getattr(self.sock, 'close_code', None)
                    self.logger.warning("Сервер камеры закрыл соединение" +
                                        (f" (WSS code {code})." if code is not None else "."))
                    if self._recover():
                        buffer = b""
                        continue
                    self.disconnect()
                    break
                
                buffer += chunk
                messages, buffer = self.sock_utils.parse_buffer(buffer)
                
                for raw_msg in messages:
                    if not raw_msg: continue
                    
                    try:
                        msg_dict = json.loads(raw_msg)
                        cmd = msg_dict.get("command")
                        
                        if cmd in ["stream_frame", "frame_response"]:
                            b64_data = msg_dict.get("image")
                            ts = msg_dict.get("timestamp", 0)
                            if b64_data:
                                self._decode_and_store_frame(b64_data, ts)
                        
                        elif cmd == "targets_response":
                            msg_dict["received_at"] = time.time()
                            
                            with self._targets_lock:
                                self._latest_targets = msg_dict
                            
                            self._targets_event.set()
                                
                    except json.JSONDecodeError:
                        pass 
                    except Exception as e:
                        self.logger.error(f"Ошибка обработки сообщения: {e}")

            except Exception as e:
                self.logger.error(f"Ошибка в listener камеры: {e}")
                if self.running:
                    self.disconnect()
                break

    def _decode_and_store_frame(self, b64_data, timestamp):
        try:
            img_data = base64.b64decode(b64_data)
            np_arr = np.frombuffer(img_data, np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            
            if frame is not None:
                with self._frame_lock:
                    self._current_frame = frame
                    self._last_frame_ts = timestamp
        except Exception:
            pass

    def _send_cmd(self, cmd_dict):
        if not self.is_connected: return
        with self._socket_lock:
            if not self.is_connected or self._stop_event.is_set(): return
            try:
                self.sock_utils.send_json(self.sock, cmd_dict)
            except Exception as e:
                self.logger.error(f"Ошибка отправки команды: {e}")
                if self.ip.startswith('wss://') and self.running:
                    # Wake the single reader; it owns reconnect and resubscription.
                    self.sock.close()
                else:
                    self.disconnect()

    def start_stream(self):
        with self._socket_lock:
            self._stream_requested = True
            self._send_cmd({"command": "get_stream"})

    def stop_stream(self):
        with self._socket_lock:
            self._stream_requested = False
            self._send_cmd({"command": "stop_stream"})

    def read(self):
        """Возвращает последний кадр: (True/False, frame)"""
        with self._frame_lock:
            if self._current_frame is not None:
                return True, self._current_frame.copy()
            else:
                return False, None

    def get_detection(self, blocking=False, timeout=2.0):
        if not self.is_connected: return None

        now = time.time()
        should_send = True
        
        if not blocking:
            if now - self._last_target_request_ts < 0.1:
                should_send = False
        
        if should_send:
            if blocking: self._targets_event.clear()
            self._send_cmd({"command": "get_target"})
            self._last_target_request_ts = now

        if blocking:
            if self._targets_event.wait(timeout=timeout):
                with self._targets_lock:
                    return dict(self._latest_targets) if self._latest_targets else None
            else:
                self.logger.warning("Таймаут получения таргетов")
                return None
        
        else:
            with self._targets_lock:
                return dict(self._latest_targets) if self._latest_targets else None

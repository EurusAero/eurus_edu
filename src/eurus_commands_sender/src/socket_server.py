import socket
import json
import threading
import configparser
import logging
import os

from EurusEdu.utils import MessagesUtils, SocketsUtils
from EurusEdu.const import START_MARKER, END_MARKER

config = configparser.ConfigParser()
config_path = '../eurus.ini'

if not os.path.exists(config_path):
    print(f"CRITICAL: Config file '{config_path}' not found!")
    exit(1)

config.read(config_path)

HOST = config['SERVER']['HOST']
PORT = int(config['SERVER']['PORT'])
BUFFER_SIZE = int(config['SERVER']['BUFFER_SIZE'])

# START_MARKER = config['PROTOCOL']['START_MARKER']
# END_MARKER = config['PROTOCOL']['END_MARKER']

LOG_LEVEL = config['LOGGING']['LEVEL'].upper()
LOG_FILE = config['LOGGING'].get('FILE', None)

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.DEBUG),
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE) if LOG_FILE else logging.NullHandler(),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("EurusServer")

# Инициализируем утилиты
msg_utils = MessagesUtils()
sock_utils = SocketsUtils(START_MARKER, END_MARKER)


def process_message(conn, json_data, addr):
    """
    Бизнес-логика обработки сообщения.
    """
    if json_data is None:
        logger.error(f"Ошибка декодирования (Unicode) от {addr}")
        sock_utils.send_json(conn, {
            "command": "response",
            "status": "error",
            "message": "Unicode decode error"
        })
        return

    try:
        # 1. Парсинг JSON
        message = json.loads(json_data)
        logger.debug(f"Сообщение от {addr}: {json.dumps(message, ensure_ascii=False)}")

        # 2. Валидация через MessagesUtils
        result = msg_utils.validate_message(message)
        logger.info(f"Валидация успешна для {addr}. Результат: {result}")

        # 3. Отправка ответа
        sock_utils.send_json(conn, {
            "command": "response",
            "status": "success",
            "message": str(result)
        })

    except json.JSONDecodeError:
        logger.warning(f"Невалидный JSON от {addr}: {json_data}")
        sock_utils.send_json(conn, {
            "command": "response",
            "status": "error",
            "message": "Invalid JSON format"
        })

    except Exception as e:
        logger.error(f"Ошибка логики для {addr}: {e}", exc_info=True)
        sock_utils.send_json(conn, {
            "command": "response",
            "status": "error",
            "message": str(e)
        })


def handle_client(conn, addr):
    """
    Цикл обработки клиента.
    """
    logger.info(f"Новый клиент подключен: {addr}")
    
    buffer = b""
    
    try:
        while True:
            chunk = conn.recv(BUFFER_SIZE)
            if not chunk:
                break 
            
            buffer += chunk

            messages, buffer = sock_utils.parse_buffer(buffer)

            for msg in messages:
                process_message(conn, msg, addr)

    except ConnectionResetError:
        logger.info(f"Соединение сброшено клиентом {addr}")
    except Exception as e:
        logger.critical(f"Критическая ошибка с клиентом {addr}: {e}", exc_info=True)
    finally:
        conn.close()
        logger.info(f"Соединение с {addr} закрыто")


def start_server():
    logger.info(f"Запуск сервера на {HOST}:{PORT}...")
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        server.bind((HOST, PORT))
        server.listen()
        logger.info("Сервер ожидает подключений...")

        while True:
            conn, addr = server.accept()
            thread = threading.Thread(target=handle_client, args=(conn, addr))
            thread.daemon = True
            thread.start()
            logger.debug(f"Активных потоков: {threading.active_count() - 1}")

    except KeyboardInterrupt:
        logger.info("Остановка сервера (KeyboardInterrupt)...")
    except Exception as e:
        logger.critical(f"Ошибка при запуске сервера: {e}", exc_info=True)
    finally:
        server.close()

if __name__ == "__main__":
    start_server()
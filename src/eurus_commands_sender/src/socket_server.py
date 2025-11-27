import socket
import json
import threading
import time
# Предполагаем, что эта библиотека у вас есть.
# Если тестируете без неё, закомментируйте импорт и использование.
from eurus_sockets.utils import MessagesUtils

# Конфигурация сервера
HOST = '127.0.0.1'
PORT = 65432

# Маркеры пакета
START_MARKER = b'<msg>'
END_MARKER = b'</msg>'

def send_response(conn, data_dict):
    """
    Утилита для отправки JSON-ответа клиенту в "обертке" маркеров.
    """
    try:
        response_json = json.dumps(data_dict)
        # Формируем пакет: <cmd>{JSON}</cmd>
        packet = START_MARKER + response_json.encode('utf-8') + END_MARKER
        conn.sendall(packet)
    except Exception as e:
        print(f"[ERROR] Не удалось отправить ответ клиенту: {e}")

def process_message(conn, json_data, addr):
    """
    Функция бизнес-логики.
    Обратите внимание: мы добавили аргумент conn, чтобы иметь возможность отвечать.
    """
    msg_utils = MessagesUtils()
    
    try:
        # 1. Пытаемся распарсить JSON
        message = json.loads(json_data)
        print(f"\n[NEW MESSAGE] От {addr}:")
        print(json.dumps(message, indent=4, ensure_ascii=False))
        
        # 2. Выполняем бизнес-логику
        # Здесь может возникнуть ошибка внутри compare_messages
        result = msg_utils.compare_messages(message)
        print(f"Результат обработки: {result}")

        # (Опционально) Можно отправить подтверждение успеха
        send_response(conn, {"status": "success", "result": str(result)})

    except json.JSONDecodeError:
        err_msg = f"[ERROR] Невалидный JSON от {addr}"
        print(err_msg)
        # Отправляем ошибку клиенту
        send_response(conn, {
            "status": "error", 
            "code": 400, 
            "message": "Invalid JSON format"
        })

    except Exception as e:
        # Ловим ошибки бизнес-логики (например, внутри msg_utils)
        err_msg = f"[ERROR] Внутренняя ошибка обработки: {e}"
        print(err_msg)
        # Отправляем ошибку клиенту
        send_response(conn, {
            "status": "error", 
            "code": 500, 
            "message": str(e)
        })


def handle_client(conn, addr):
    """
    Обработчик отдельного клиента.
    """
    print(f"[CONNECTION] Новый клиент подключен: {addr}")
    
    buffer = b""
    
    try:
        while True:
            chunk = conn.recv(1024)
            if not chunk:
                break 
            
            buffer += chunk

            while True:
                start_index = buffer.find(START_MARKER)
                end_index = buffer.find(END_MARKER, start_index) if start_index != -1 else -1

                if start_index != -1 and end_index != -1:
                    payload = buffer[start_index + len(START_MARKER) : end_index]
                    
                    # Очистка буфера СРАЗУ, чтобы не потерять хвост при ошибке декодирования
                    buffer = buffer[end_index + len(END_MARKER):]
                    
                    try:
                        decoded_payload = payload.decode('utf-8')
                        # Передаем conn в функцию обработки
                        process_message(conn, decoded_payload, addr)
                        
                    except UnicodeDecodeError:
                        print(f"[ERROR] Ошибка кодировки от {addr}")
                        send_response(conn, {
                            "status": "error", 
                            "code": 400, 
                            "message": "Unicode decode error"
                        })
                else:
                    break
            
            # Небольшая задержка, чтобы не грузить CPU в цикле while True (хотя recv блокирующий)
            # В данном месте она может быть полезной, если буфер обрабатывается быстрее поступления данных
            # time.sleep(0.01) 

    except ConnectionResetError:
        print(f"[DISCONNECT] Соединение сброшено клиентом {addr}")
    except Exception as e:
        print(f"[ERROR] Критическая ошибка с клиентом {addr}: {e}")
    finally:
        conn.close()
        print(f"[CLOSED] Соединение с {addr} закрыто")

def start_server():
    print(f"[STARTING] Сервер запускается на {HOST}:{PORT}...")
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        server.bind((HOST, PORT))
        server.listen()
        print("[LISTENING] Сервер ожидает подключений...")

        while True:
            conn, addr = server.accept()
            thread = threading.Thread(target=handle_client, args=(conn, addr))
            thread.daemon = True
            thread.start()
            print(f"[ACTIVE CONNECTIONS] {threading.active_count() - 1}")

    except KeyboardInterrupt:
        print("\n[STOPPING] Остановка сервера...")
    finally:
        server.close()

if __name__ == "__main__":
    start_server()
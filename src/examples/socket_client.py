import socket
import json

SERVER_HOST = '127.0.0.1'
SERVER_PORT = 65432

# Определяем маркеры (разделители)
# Лучше сразу определять их как байты (b'string')
START_MARKER = b'<msg>'
END_MARKER = b'</msg>'

def run_client():
    data = {
        "command": "tako",
        "altitude": 123, 
        }
    

    try:
        # 1. Сериализация в JSON
        json_string = json.dumps(data)
        
        # 2. Кодирование тела сообщения в байты
        body_bytes = json_string.encode('utf-8')

        # 3. Формирование полного пакета:
        # [МАРКЕР НАЧАЛА] + [JSON ДАННЫЕ] + [МАРКЕР КОНЦА]
        packet = START_MARKER + body_bytes + END_MARKER

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            print(f"Подключение к {SERVER_HOST}:{SERVER_PORT}...")
            s.connect((SERVER_HOST, SERVER_PORT))

            # 4. Отправка пакета
            s.sendall(packet)
            
            # Для отладки выводим, что реально ушло в сеть
            print(f"Отправлено байт: {len(packet)}")
            print(f"Содержимое пакета: {packet}")

    except ConnectionRefusedError:
        print("Ошибка: Не удалось подключиться к серверу.")
    except Exception as e:
        print(f"Произошла ошибка: {e}")

if __name__ == "__main__":
    run_client()
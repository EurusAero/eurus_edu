import cv2
import time
import numpy as np
from EurusEdu import EurusCamera

def draw_targets(frame, targets_data):
    """
    Функция для отрисовки всех найденных целей на кадре.
    """
    if not targets_data or "all_targets" not in targets_data:
        return

    # Проверяем свежесть данных (опционально)
    data_age = time.time() - targets_data.get("received_at", time.time())
    if data_age > 0.5:
        return 

    for target in targets_data["all_targets"]:
        try:
            # Получаем данные из JSON
            cx = target['x'] # Центр по X
            cy = target['y'] # Центр по Y
            w = target['w']  # Ширина
            h = target['h']  # Высота
            cls_name = target['class']
            conf = target.get('conf', 0.0)

            # --- Конвертация координат ---
            top_left_x = int(cx - w / 2)
            top_left_y = int(cy - h / 2)
            bottom_right_x = int(cx + w / 2)
            bottom_right_y = int(cy + h / 2)

            # --- Выбор цвета ---
            color = (0, 255, 0) # Зеленый по умолчанию
            if "red" in cls_name:
                color = (0, 0, 255) # Красный
            elif "blue" in cls_name:
                color = (255, 0, 0) # Синий

            # --- Рисование ---
            # Прямоугольник
            cv2.rectangle(frame, (top_left_x, top_left_y), (bottom_right_x, bottom_right_y), color, 2)
            
            # --- Текст над прямоугольником (ИЗМЕНЕНО) ---
            # Добавили W (width) и H (height), округлив до целого числа int()
            label = f"{cls_name} {conf:.2f} W:{int(w)} H:{int(h)}"
            
            cv2.putText(frame, label, (top_left_x, top_left_y - 10), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

        except KeyError:
            continue

def main():
    # Укажите актуальный IP адрес
    cam = EurusCamera("192.168.31.166", 8001)

    try:
        cam.connect()
        cam.start_stream()
        
        # Даем немного времени на буферизацию
        time.sleep(1)

        print("Нажмите 'q' для выхода")

        while True:
            # 1. Читаем кадр (не блокирует)
            ret, frame = cam.read()
            
            if ret:
                # 2. Запрашиваем таргеты
                targets = cam.get_targets(blocking=False)
                
                # 3. Рисуем прямоугольники на кадре
                if targets:
                    draw_targets(frame, targets)

                # 4. Показываем результат
                cv2.imshow("Drone Feed + YOLO", frame)
        
            # Выход по кнопке 'q'
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
                
    except KeyboardInterrupt:
        print("Stopping by Ctrl+C...")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        cam.stop_stream()
        cam.disconnect()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
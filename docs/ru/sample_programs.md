# Примеры программ

### Взлёт и посадка

``` python
from EurusEdu import EurusControl
import time

drone = drone("10.42.0.1", 65432)
drone.connect()

drone.arm()
drone.takeoff(1.5)

time.sleep(6)  # Ждём стабилизации

drone.land()
drone.disconnect()
```
*После каждого takeoff() локальные координаты сбрасываются в (0, 0, 0)*


### Полёт к локальной точке

``` python
from EurusEdu import EurusControl
import time

drone = drone("10.42.0.1", 65432)
drone.connect()
time.sleep(3)

drone.arm()
drone.takeoff(1)

time.sleep(5)

# Летим на 2 метра вперёд и поворачиваемся на 90°
drone.move_to_local_point(
    x=2,
    y=0,
    z=1,
    yaw=90
)

time.sleep(5)
drone.land()
```


### Движение относительно текущей позиции (Body Frame)

``` python
from EurusEdu import EurusControl
import time

drone = drone("10.42.0.1", 65432)
drone.connect()

drone.arm()
drone.takeoff(1.5)
time.sleep(5)

# Диагональный полёт вперёд-влево
drone.move_in_body_frame(
    x=3,   # вперёд
    y=4,   # влево
    z=1.5, # текущая высота
    yaw=0
)

time.sleep(5)
drone.land()
```


### Полёт по квадрату

``` python
import time
from EurusEdu import EurusControl

def run_square_mission():
    # --- НАСТРОЙКИ ---
    IP_ADDRESS = "10.42.0.1"
    PORT = 65432
    ALTITUDE = 1              
    SIDE_LENGTH = 0.5            
    LAPS = 1                     

    # Настройки LED
    # Количество светодиодов
    LEDS_COUNT = 20 

    drone = EurusControl(ip=IP_ADDRESS, port=PORT)

    try:
        drone.connect()
        time.sleep(1)

        if not drone.is_connected:
            print("Не удалось подключиться к дрону.")
            return

        print("Начало миссии")

        # 1. ПОДГОТОВКА И ВЗЛЕТ (Эффект: BLINK, Желтый)
        print("Включаем мигание (желтый) перед взлетом...")
        drone.led_control(effect="blink", r=255, g=255, b=0, nLED=LEDS_COUNT)

        print("Арминг...")
        drone.arm()

        print(f"Взлет на высоту {ALTITUDE}м...")
        drone.takeoff(ALTITUDE)

        # Пауза, чтобы дрон стабилизировался перед полетом
        time.sleep(7)

        # 2. ПОЛЕТ ПО КВАДРАТУ
        print("Включаем эффект 'komet' (синий) для полета...")
        drone.led_control(effect="komet", r=0, g=0, b=255, nLED=LEDS_COUNT)

        for lap in range(1, LAPS + 1):
            print(f"\n--- Круг №{lap} ---")

            # Точка 1
            drone.move_to_local_point(x=SIDE_LENGTH, y=0, z=ALTITUDE)
            time.sleep(5)
            # Точка 2
            drone.move_to_local_point(x=SIDE_LENGTH, y=SIDE_LENGTH, z=ALTITUDE)
            time.sleep(5)
            # Точка 3
            drone.move_to_local_point(x=0, y=SIDE_LENGTH, z=ALTITUDE)
            time.sleep(5)
            # Точка 4 (Возврат)
            drone.move_to_local_point(x=0, y=0, z=ALTITUDE)
            time.sleep(5)

        print("\nПолетная программа завершена.")

    except KeyboardInterrupt:
        print("\nМиссия прервана пользователем!")
    except Exception as e:
        print(f"\nПроизошла ошибка: {e}")
    finally:
        # 3. ПОСАДКА
        if drone.is_connected:
            print("Включаем мигание (красный) для посадки...")
            drone.led_control(effect="blink", r=255, g=0, b=0, nLED=LEDS_COUNT)

            print("Приземление...")
            drone.land()

            # Ждем пока сядет
            time.sleep(3) 

            # Выключаем ленту перед разрывом соединения
            print("Выключение подсветки...")
            drone.led_control(effect="static", r=0, g=0, b=0, nLED=LEDS_COUNT)

            print("Отключение...")
            drone.disconnect()

if __name__ == "__main__":
    run_square_mission()
```


### Проверка светодиодной ленты

``` python
from EurusEdu import EurusControl
import time

drone = EurusControl("192.168.31.164", 65432)

drone.connect()
time.sleep(1)
print("Базовый режим - режим кометы с белым цветом")
drone.led_control("base")
time.sleep(5)
print("Статическое свечение")
drone.led_control("static", 255, 255, 0, brightness=0.5)
time.sleep(5)
print("Радуга")
drone.led_control("rainbow")
time.sleep(5)
print("Комета")
drone.led_control("komet", 255, 0, 0)
time.sleep(5)
drone.led_control(effect="blink", r=255, g=255, b=255, nLED=16, brightness=0.1)
time.sleep(5)
```


### Отображение видеопотока с камеры дрона с визуализацией объектов, обнаруженных нейросетью YOLO.

``` python
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
```
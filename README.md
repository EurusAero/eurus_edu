# Eurus-Edu

Репозиторий образовательного дрона

# Docs

-   Создание объектов дрона и камеры

    drone = EurusControl(ip, drone_port)

    входные параметры:

    -   ip: str ip
    -   port: int порт
    -   console_log: bool true для логирования
    -   log_file: str файл для логирования

    camera = EurusCamera(ip, camera_port)

-   Подключение к ним

    drone.connect()

    camera.connect()

-   Запуск видеопотока.

    camera.start_stream()

## Методы объекта дрона

### подключение

connect()

### отключение

disconnect()

### Установка режима

set_mode()

### Арм дрона

arm()

### Дизарм дрона

disarm()

### Взлёт дрона

takeoff(altitude : float)

Входные параметры:

-   altitude высота

### Посадка дрона

land()

### Двигатся к локальной точке

move_to_local_point(x, y, z, yaw)

Входные параметры:

-   x
-   y
-   z
-   yaw поворот

### двигатся к точке в координате относительно текущей позиции

move_in_body_frame(x, y, z, yaw)

Входные параметры:

-   x
-   y
-   z
-   yaw поворот

### Установка скорости

set_velocity(self, vx, vy, vz, yaw_rate)

Входные параметры:

-   vx скорость по х
-   vy скорость по у
-   vz скорость по z
-   yaw_rate скорость поворота

### Лазерная пушка

pin лазерa = 13

drone.laser_shot()

Отправляет команду выстрела.
Не блокирует другие команды управления (можно вызывать параллельно с полетом).
Блокирует только текущий поток на ~0.5 сек до получения ответа о выстреле.

выходные параметры:

-   Если выстрелить получилось возвращает true иначе false

### Получение телеметрии

request_telemetry()

Выходные параметры:

-если тееметрии нет вернёт None если есть кинет telemetry data

telemetry_data:

-   state

    -   telemetry_data["state"]["connected"] = self.state_msg.connected
    -   telemetry_data["state"]["armed"] = self.state_msg.armed
    -   telemetry_data["state"]["mode"] = self.state_msg.mode
    -   telemetry_data["state"]["system_status"] = self.state_msg.system_status

-   battery

    -   telemetry_data["battery"]["voltage"] = self.battery_msg.voltage
    -   telemetry_data["battery"]["cell_voltage"] = list(self.battery_msg.cell_voltage)
    -   telemetry_data["battery"]["current"] = self.battery_msg.current
    -   telemetry_data["battery"]["percentage"] = int(self.battery_msg.percentage \* 100)

-   local_position

    -   telemetry_data["local_position"]["x"] = pose.x
    -   telemetry_data["local_position"]["y"] = pose.y
    -   telemetry_data["local_position"]["z"] = pose.z
    -   telemetry_data["local_position"]["roll"] = degrees(orientation_angles[0])
    -   telemetry_data["local_position"]["pitch"] = degrees(orientation_angles[1])
    -   telemetry_data["local_position"]["yaw"] = degrees(orientation_angles[2])

-   setpoint_local

    -   telemetry_data["setpoint_local"]["x"] = setpoint_pose.x
    -   telemetry_data["setpoint_local"]["y"] = setpoint_pose.y
    -   telemetry_data["setpoint_local"]["z"] = setpoint_pose.z
    -   telemetry_data["setpoint_local"]["yaw"] = degrees(setpoint_orientation_angles[2])

-   velocity

    -   telemetry_data["velocity"]["vx"] = velocity.x
    -   telemetry_data["velocity"]["vy"] = velocity.y
    -   telemetry_data["velocity"]["vz"] = velocity.z

-   point_reached

    -   telemetry_data["point_reached"] = point_reached (bool)

### LED

led_control(effect)

Входные параметры:

-   effect (string) - режим свечения
    Режимы:
    "base" - тупо светится синим
    "static" - тупо светится выбраным цветом с выбранными парметрами
    "rainbow" - радуга
    "komet" - бегает по ленте выбранным цветом
    "blink" - мигает выбранным цветом
-   r красный компонент цвета свечения
-   g зелёный компонент цвета свечения
-   b синий компонент цвета свечения
-   nLED
-   brightness яркость свечения

## Методы объекта камеры

### подключение

connect()

### отключение

disconnect()

### запуск видео потока

start_stream()

### остоновка видео потока

stop_stream()

### Чтение кадра

read()

### получение целей

get_targets()

# TODO

Динамическое присваивание портов, проверка что он не занят (например если 8000 не занят, то берем его, если занят, то 8001 и тд, с камерой тоже самое)

Сделать получше конфигурацию светодиодной ленты

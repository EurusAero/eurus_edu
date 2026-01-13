# Eurus-Edu

Репозиторий образовательного дрона

# Docs

## Создание объектов дрона и камеры

```python
drone = EurusControl(ip, drone_port)
camera = EurusCamera(ip, camera_port)
```

**Входные параметры:**

-   ```ip```: str ip
-   ```port```: int порт
-   ```console_log```: bool true для логирования
-   ```log_file```: str файл для логирования

## Подключение к ним

```python
drone.connect()
camera.connect()
```

## Запуск видеопотока

```python
camera.start_stream()
```

# Методы объекта дрона

## Подключение

```python
connect()
```

## Отключение

```python
disconnect()
```

## Установка режима

```python
set_mode()
```

## Арм дрона

```python
arm()
```

## Дизарм дрона

```python
disarm()
```

## Взлёт дрона

```python
takeoff(altitude : float)
```

**Примечание:** При каждом взлёте текущие локальные координаты дрона становятся (0, 0, 0)

**Входные параметры:**

-   ```altitude```: высота

**Пример:**

``` python

z = 1.5

drone.takeoff(z)
time.sleep(6) # Дрон взлетает на высоту 1.5 метра и стабилизируется

```

## Посадка дрона

```python
land() # Дрон плавно снижает высоту и садится
```

## Двигаться к локальной точке

```python
move_to_local_point(x, y, z, yaw)
```

**Входные параметры:**

-   ```x```
-   ```y```
-   ```z```
-   ```yaw```: поворот (в градусах)

**Пример:**

``` python

drone.takeoff(1)
time.sleep(5)

x = 2
y = 0
z = 1
yaw = 90

drone.move_to_local_point(x, y, z, yaw) # Дрон летит на 2 метра вперёд и разворачивается на 90 градусов

```

## Двигаться к точке в координате относительно текущей позиции

```python
move_in_body_frame(x, y, z, yaw)
```

**Входные параметры:**

-   ```x``` - Целевая позиция по координате X (вперед от текущей позиции)
-   ```y``` - Целевая позиция по координате Y (влево от текущей позиции)
-   ```z``` - Целевая позиция по координате Z (относительно земли)
-   ```yaw``` - Рыскание (в градусах)

**Пример:**

```python

x = 4
y = 3
z = 1
drone.takeoff(z)
time.sleep(6)
drone.move_in_body_frame(x, y, z) # Дрон пролетит по диагонали (вперед-влево) на 5 метров, сохраняя текущую высоту

```

## Установка скорости

```python
set_velocity(vx, vy, vz, yaw_rate)
```

**Входные параметры:**

-   ```vx``` - скорость по х
-   ```vy``` - скорость по у
-   ```vz``` - скорость по z
-   ```yaw_rate``` -- скорость поворота

**Пример:**

``` python

drone.takeoff(1)
time.sleep(5)

drone.set_velocity(
    vx = 0.5, # Движение вперёд
    vy = 0, # Без бокового вращения
    vz = 0, # Без изменения высоты
    yaw_rate = 20 # Вращение вокруг оси
)

time.sleep(3)
drone.set_velocity(0, 0, 0, 0) # Останавливаем движение

```

## Лазерная пушка

pin лазерa = 13

```python
drone.laser_shot()
```
**Примечание:**
-   Отправляет команду выстрела.
-   Не блокирует другие команды управления (можно вызывать параллельно с полетом).
-   Блокирует только текущий поток на ~0.5 сек до получения ответа о выстреле.

**Выходные параметры:**

-   Если выстрелить получилось возвращает true, иначе - false

**Пример:**

``` python

drone.takeoff(1)
time.sleep(5)

result = drone.laser_shot()

if result:
    print("Выстрел выполнен")
else:
    print("Ошибка выстрела")

```

## Получение телеметрии

```python
request_telemetry()
```

**Возвращаемые значения:**

-   None, если телеметрии нет,
-   Telemetry data, если телеметрия получена.

**Пример:**

``` python

telemetry = drone.request_telemetry() # Запрашиваем телеметрию

if telemetry is not None:
    print("Высота:", telemetry["local_position"]["z"]) # Теущая высота
    print("Заряд батареи:", telemetry["battery"]["percentage"], "%") # Уровень заряда батареи

```

**Структура telemetry_data:**

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

## LED

```python
led_control(effect)
```

**Входные параметры:**

-   ```effect (string)``` - режим свечения

**Режимы:**

-   ```base``` - тупо светится синим
-   ```static``` - светится выбраным цветом с выбранными парметрами
-   ```rainbow``` - радуга
-   ```komet``` - бегает по ленте выбранным цветом
-   ```blink``` - мигает выбранным цветом

**Дополнительные параметры:**

-   ```r``` - красный компонент цвета свечения
-   ```g``` - зелёный компонент цвета свечения
-   ```b``` - синий компонент цвета свечения
-   ```nLED``` - количество светодиодов
-   ```brightness``` - яркость свечения

**Пример:**
``` python
# Красная подсветка
drone.led_control(
    effect="static",
    r=255,
    g=0,
    b=0,
    brightness=200
)

# Радужный эффект
drone.led_control(effect="rainbow")
```

# Методы объекта камеры

## Подключение

```python
connect()
```

## Отключение

```python
disconnect()
```

## Запуск видео потока

```python
start_stream()
```

## Остановка видео потока

```python
stop_stream()
```

## Чтение кадра

```python
read()
```

## Получение целей

```python
get_targets()
```

# TODO

-   Динамическое присваивание портов, проверка что он не занят (например если 8000 не занят, то берем его, если занят, то 8001 и тд, с камерой тоже самое)

-   Сделать получше конфигурацию светодиодной ленты

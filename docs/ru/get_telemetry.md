# Получение телеметрии

**Подключение:**

```python
drone.get_telemetry()
```

**Возвращаемые значения:**

- none - не удалось получить телеметрию
- Telemetry data - телеметрия получена

​
**Структура telemetry_data:**

- state
    - `connected` — есть ли соединение
    - `armed` — состояние моторов
    - `mode` — текущий режим
    - `system_status` — состояние системы

- battery
    - `voltage` - напряжение (В)
    - `cell_voltage` - напряжение на одну ячейку (В)
    - `current` - ток (А)
    - `percentage` — заряд (%)

- local_position
    - `x, y, z` - позиция (м)
    - `roll, pitch, yaw` - углы (градусы)

- velocity
    - `vx, vy, vz`- скорости (м/с)

- aruco_map - сообщения о статусе навигации по аруко
    - `timestamp` - время последнего сообщения
    - `aruco_navigation_status` - включена ли навигация по аруко маркерам
    - `map_in_vision` - статус видимости аруко карты
    - `fly_in_borders` - включена ли виртуальная стена

- setpoint_raw
    - `type_mask`- маска управления
    - `vx` - заданная скорость по оси Х
    - `vy` - заданная скорость по оси Y
    - `vz` - заданная скорость по оси Z
    - `x` - заданная позиция по оси Х
    - `y` - заданная позиция по оси Y
    - `z` - заданная позиция по оси Z
    - `yaw` - заданное рысканье
    - `yaw_rate` - заданная угловая скорость рысканья

- point_reached
    - `True` - целевая точка достигнута
    - `False` - целевая точка не достигнута

- is_alive - статус дрона в игре

**Пример получения телеметрии на Python:**

```python​
telemetry = drone.get_telemetry() # Запрашиваем телеметрию
​
​
if telemetry is not None:
​
    print("Высота:", telemetry["local_position"]["z"]) # Теущая высота
​
    print("Заряд батареи:", telemetry["battery"]["percentage"], "%") # Уровень заряда батареи
```
